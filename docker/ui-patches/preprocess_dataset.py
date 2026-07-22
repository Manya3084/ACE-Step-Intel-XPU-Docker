#!/usr/bin/env python3
"""Preprocess ACE-Step dataset JSON -> .pt tensors (Intel XPU Docker).

- DatasetBuilder.load_dataset() (not load_from_dict)
- AceStepHandler.initialize_service()
- soundfile audio load (TorchCodec is CUDA-only / needs libnvrtc)
- Coerces genre_ratio to float; forces samples labeled

Usage:
  python preprocess_dataset.py \\
    --dataset /app/datasets/my_lora_dataset.json \\
    --output /app/datasets/preprocessed_tensors \\
    --max-duration 240 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def _ensure_labeled(dataset_path: Path) -> dict:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    for s in samples:
        s["labeled"] = True
        if not (s.get("caption") or "").strip():
            s["caption"] = "instrumental, high quality music"
        if not (s.get("lyrics") or "").strip():
            s["lyrics"] = "[Instrumental]"
        ap = s.get("audio_path") or ""
        if not ap:
            continue
        p = Path(ap)
        # Prefer companion .wav when original is mp3/flac (soundfile-friendly)
        wav = p.with_suffix(".wav")
        if wav.is_file():
            s["audio_path"] = str(wav)
            s["filename"] = wav.name
            p = wav
        if not p.is_file():
            raise FileNotFoundError(f"audio missing: {p}")
    data["samples"] = samples
    meta = data.get("metadata") or {}
    gr = meta.get("genre_ratio", 0)
    if isinstance(gr, dict):
        gr = gr.get("ratio", gr.get("value", 0)) or 0
    try:
        meta["genre_ratio"] = float(gr)
    except Exception:
        meta["genre_ratio"] = 0.0
    meta["num_samples"] = len(samples)
    meta.setdefault("name", dataset_path.stem)
    data["metadata"] = meta
    dataset_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _patch_soundfile_audio_load() -> None:
    """TorchCodec fails on pure XPU (libnvrtc). Use soundfile instead."""
    import torch
    import soundfile as sf
    import acestep.training.dataset_builder_modules.preprocess_audio as pa
    import acestep.training.dataset_builder_modules.preprocess as preprocess_mod

    def load_audio_stereo(audio_path, target_sample_rate=48000, max_duration=240.0):
        data, sr = sf.read(str(audio_path), always_2d=True)
        audio = torch.from_numpy(data.T).float()
        if audio.shape[0] == 1:
            audio = audio.repeat(2, 1)
        elif audio.shape[0] > 2:
            audio = audio[:2]
        if sr != target_sample_rate:
            audio = torch.nn.functional.interpolate(
                audio.unsqueeze(0),
                size=int(audio.shape[1] * target_sample_rate / float(sr)),
                mode="linear",
                align_corners=False,
            ).squeeze(0)
        max_len = int(max_duration * target_sample_rate)
        if audio.shape[1] > max_len:
            audio = audio[:, :max_len]
        return audio, target_sample_rate

    pa.load_audio_stereo = load_audio_stereo
    preprocess_mod.load_audio_stereo = load_audio_stereo
    print("[preprocess] patched load_audio_stereo -> soundfile", file=sys.stderr)


def _init_dit_handler():
    from acestep.handler import AceStepHandler

    root = os.environ.get("ACESTEP_CHECKPOINTS", "/app/checkpoints")
    if not Path(root).is_dir():
        root = os.environ.get("ACESTEP_PATH", "/app")
    config_path = Path(
        os.environ.get("ACESTEP_CONFIG_PATH")
        or os.environ.get("ACESTEP_DIT_MODEL")
        or "acestep-v15-turbo"
    ).name
    device = os.environ.get("PYTORCH_DEVICE") or os.environ.get("ACESTEP_DEVICE") or "xpu"
    offload = (os.environ.get("ACESTEP_OFFLOAD_TO_CPU", "true") or "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    h = AceStepHandler()
    status, ok = h.initialize_service(
        project_root=str(root),
        config_path=config_path,
        device=device,
        use_flash_attention=False,
        compile_model=False,
        offload_to_cpu=offload,
        offload_dit_to_cpu=False,
    )
    print(f"[preprocess] initialize_service ok={ok} status={status}", file=sys.stderr)
    if not ok and getattr(h, "model", None) is None and getattr(h, "vae", None) is None:
        raise RuntimeError(f"initialize_service failed: {status}")
    return h


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess dataset to tensors for LoRA training (XPU)")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-duration", type=float, default=240.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_path.is_file():
        err = {"ok": False, "error": f"Dataset file not found: {dataset_path}"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    try:
        _ensure_labeled(dataset_path)
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        print(json.dumps(err) if args.json else str(e))
        return 1

    try:
        _patch_soundfile_audio_load()
    except Exception as e:
        err = {"ok": False, "error": f"soundfile patch failed: {e}"}
        print(json.dumps(err) if args.json else str(e))
        traceback.print_exc()
        return 1

    print(f"Loading dataset: {dataset_path}", file=sys.stderr)
    try:
        from acestep.training.dataset_builder import DatasetBuilder
    except Exception as e:
        err = {"ok": False, "error": f"import DatasetBuilder failed: {e}"}
        print(json.dumps(err) if args.json else err["error"])
        traceback.print_exc()
        return 1

    builder = DatasetBuilder()
    try:
        samples, load_msg = builder.load_dataset(str(dataset_path))
    except Exception as e:
        err = {"ok": False, "error": f"load_dataset failed: {e}"}
        print(json.dumps(err) if args.json else err["error"])
        traceback.print_exc()
        return 1

    print(load_msg, file=sys.stderr)
    if not samples:
        err = {"ok": False, "error": f"No samples loaded: {load_msg}"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    for s in builder.samples:
        if hasattr(s, "labeled"):
            s.labeled = True
    gr = getattr(builder.metadata, "genre_ratio", 0)
    if isinstance(gr, dict):
        gr = 0
    try:
        builder.metadata.genre_ratio = float(gr or 0)
    except Exception:
        builder.metadata.genre_ratio = 0.0

    print(f"Initializing DiT handler ({len(builder.samples)} samples)...", file=sys.stderr)
    try:
        dit_handler = _init_dit_handler()
    except Exception as e:
        err = {
            "ok": False,
            "error": str(e),
            "hint": "AceStepHandler.initialize_service failed; check /app/checkpoints",
            "samples_loaded": len(builder.samples),
        }
        print(json.dumps(err) if args.json else str(e))
        traceback.print_exc()
        return 1

    print("Running preprocess_to_tensors...", file=sys.stderr)
    try:
        try:
            paths, status = builder.preprocess_to_tensors(
                dit_handler=dit_handler,
                output_dir=str(output_dir),
                max_duration=args.max_duration,
                preprocess_mode="lora",
            )
        except TypeError:
            paths, status = builder.preprocess_to_tensors(
                dit_handler,
                str(output_dir),
                max_duration=args.max_duration,
            )
    except Exception as e:
        err = {"ok": False, "error": str(e), "samples_loaded": len(builder.samples)}
        print(json.dumps(err) if args.json else str(e))
        traceback.print_exc()
        return 1

    result = {
        "ok": True,
        "status": status,
        "count": len(paths) if paths else 0,
        "paths": [str(p) for p in (paths or [])],
        "samples_loaded": len(builder.samples),
        "output": str(output_dir),
    }
    print(json.dumps(result) if args.json else status)
    return 0 if result["count"] else 1


if __name__ == "__main__":
    sys.exit(main())
