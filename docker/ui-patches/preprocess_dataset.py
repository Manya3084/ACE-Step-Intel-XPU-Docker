#!/usr/bin/env python3
"""Standalone dataset preprocessor for ACE-Step LoRA training (XPU Docker).

Converts labeled samples from dataset JSON into .pt tensors.
Uses DatasetBuilder.load_dataset() — NOT load_from_dict (removed upstream).
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
        if ap and not Path(ap).is_file():
            raise FileNotFoundError(f"audio missing: {ap}")
    data["samples"] = samples
    meta = data.get("metadata") or {}
    meta["num_samples"] = len(samples)
    meta.setdefault("name", dataset_path.stem)
    data["metadata"] = meta
    dataset_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _init_dit_handler():
    """Best-effort AceStepHandler init across ACE-Step versions."""
    last_err = None
    # Pattern 1: core handler class
    try:
        from acestep.core.generation.handler import AceStepHandler  # type: ignore

        h = AceStepHandler()
        for meth in ("initialize_service", "initialize", "init_service", "setup"):
            fn = getattr(h, meth, None)
            if callable(fn):
                try:
                    fn()
                    break
                except TypeError:
                    try:
                        fn(None)
                        break
                    except Exception as e:
                        last_err = e
                except Exception as e:
                    last_err = e
        if getattr(h, "model", None) is not None:
            return h
    except Exception as e:
        last_err = e

    # Pattern 2: service from generation package
    try:
        from acestep.core.generation import service as gen_service  # type: ignore

        if hasattr(gen_service, "get_handler"):
            h = gen_service.get_handler()
            if h is not None:
                return h
    except Exception as e:
        last_err = e

    raise RuntimeError(f"Could not initialize DiT handler: {last_err}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess dataset to tensors for LoRA training")
    parser.add_argument("--dataset", required=True, help="Path to dataset JSON file")
    parser.add_argument("--output", required=True, help="Output directory for tensor files")
    parser.add_argument("--max-duration", type=float, default=240.0, help="Max audio duration in seconds")
    parser.add_argument("--json", action="store_true", help="Output JSON summary")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_path.is_file():
        err = {"ok": False, "error": f"Dataset file not found: {dataset_path}"}
        print(json.dumps(err) if args.json else err["error"], file=sys.stderr if not args.json else sys.stdout)
        return 1

    try:
        _ensure_labeled(dataset_path)
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        print(json.dumps(err) if args.json else str(e))
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

    # Force labeled on builder samples
    for s in builder.samples:
        if hasattr(s, "labeled"):
            s.labeled = True

    print(f"Initializing DiT handler for preprocess ({len(builder.samples)} samples)...", file=sys.stderr)
    try:
        dit_handler = _init_dit_handler()
    except Exception as e:
        err = {
            "ok": False,
            "error": str(e),
            "hint": "Need AceStepHandler with model loaded; check checkpoints and VRAM",
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
        "paths": paths or [],
        "samples_loaded": len(builder.samples),
        "output": str(output_dir),
    }
    print(json.dumps(result) if args.json else status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
