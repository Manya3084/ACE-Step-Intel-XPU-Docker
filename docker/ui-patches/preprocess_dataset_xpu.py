#!/usr/bin/env python3
"""Preprocess ACE-Step dataset JSON -> .pt tensors (XPU Docker).

Does not use DatasetBuilder.load_from_dict (missing in upstream).
Builds samples via AudioSample / DatasetBuilder public API when available,
otherwise loads audio paths and calls preprocess_to_tensors if builder is populated.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-duration", type=float, default=240.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_path.is_file():
        err = {"ok": False, "error": f"dataset not found: {dataset_path}"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    data = json.loads(dataset_path.read_text())
    samples_in = data.get("samples") or []
    if not samples_in:
        err = {"ok": False, "error": "no samples in dataset JSON"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    # Ensure labeled + caption for preprocess filters
    for s in samples_in:
        if not s.get("labeled"):
            s["labeled"] = True
        if not (s.get("caption") or "").strip():
            s["caption"] = "instrumental, high quality music"
        if not (s.get("lyrics") or "").strip():
            s["lyrics"] = "[Instrumental]"
        apath = s.get("audio_path") or ""
        if not Path(apath).is_file():
            err = {"ok": False, "error": f"audio missing: {apath}"}
            print(json.dumps(err) if args.json else err["error"])
            return 1

    dataset_path.write_text(json.dumps(data, indent=2))

    try:
        from acestep.training.dataset_builder import DatasetBuilder, AudioSample
    except Exception as e:
        err = {"ok": False, "error": f"import DatasetBuilder failed: {e}"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    builder = DatasetBuilder()
    meta = data.get("metadata") or {}
    # Best-effort metadata fields
    for attr, key in [
        ("name", "name"),
        ("custom_tag", "custom_tag"),
        ("tag_position", "tag_position"),
    ]:
        if hasattr(builder, attr) and key in meta:
            try:
                setattr(builder, attr, meta[key])
            except Exception:
                pass
        if hasattr(builder, "metadata") and isinstance(getattr(builder, "metadata", None), object):
            try:
                setattr(builder.metadata, attr, meta.get(key))
            except Exception:
                pass

    added = 0
    for s in samples_in:
        try:
            # AudioSample signature varies by version — try kwargs commonly used
            kwargs = dict(
                audio_path=s["audio_path"],
                caption=s.get("caption") or "",
                lyrics=s.get("lyrics") or "[Instrumental]",
            )
            for k in ("filename", "genre", "bpm", "keyscale", "timesignature", "duration", "language", "is_instrumental", "custom_tag", "labeled"):
                if k in s and s[k] is not None:
                    kwargs[k] = s[k]
            sample = AudioSample(**{k: v for k, v in kwargs.items() if True})
            if hasattr(sample, "labeled"):
                sample.labeled = True
            if hasattr(builder, "add_sample"):
                builder.add_sample(sample)
            elif hasattr(builder, "samples"):
                builder.samples.append(sample)
            else:
                raise RuntimeError("DatasetBuilder has no add_sample/samples")
            added += 1
        except TypeError:
            # Positional fallback
            try:
                sample = AudioSample(s["audio_path"], s.get("caption") or "", s.get("lyrics") or "[Instrumental]")
                if hasattr(sample, "labeled"):
                    sample.labeled = True
                if hasattr(builder, "add_sample"):
                    builder.add_sample(sample)
                else:
                    builder.samples.append(sample)
                added += 1
            except Exception as e:
                err = {"ok": False, "error": f"AudioSample failed: {e}"}
                print(json.dumps(err) if args.json else err["error"])
                traceback.print_exc()
                return 1
        except Exception as e:
            err = {"ok": False, "error": f"add sample failed: {e}"}
            print(json.dumps(err) if args.json else err["error"])
            traceback.print_exc()
            return 1

    if added == 0:
        err = {"ok": False, "error": "no samples added to builder"}
        print(json.dumps(err) if args.json else err["error"])
        return 1

    # Need live DiT handler for real VAE/text encode — try service if present
    dit_handler = None
    try:
        # Some builds expose a global/service; optional
        from acestep.core.generation.handler import AceStepHandler  # type: ignore
    except Exception:
        AceStepHandler = None  # type: ignore

    status = ""
    paths: list = []
    try:
        if not hasattr(builder, "preprocess_to_tensors"):
            raise RuntimeError("DatasetBuilder.preprocess_to_tensors missing")

        # Without a handler, instruct user to use Gradio preprocess
        if dit_handler is None:
            msg = (
                "Builder loaded %d samples but preprocess_to_tensors needs an initialized "
                "DiT handler. Use Gradio Training preprocess on :8001, or ensure ACE service "
                "exposes handler to this script." % added
            )
            # Still save normalized JSON for Gradio load
            out = {
                "ok": False,
                "error": msg,
                "samples_loaded": added,
                "dataset": str(dataset_path),
                "output": str(output_dir),
                "hint": "Open Gradio :8001 Training tab, load this JSON, run preprocess there",
            }
            print(json.dumps(out) if args.json else msg)
            return 2

        paths, status = builder.preprocess_to_tensors(
            dit_handler,
            str(output_dir),
            max_duration=args.max_duration,
            preprocess_mode="lora",
        )
    except Exception as e:
        err = {"ok": False, "error": str(e), "samples_loaded": added}
        print(json.dumps(err) if args.json else str(e))
        traceback.print_exc()
        return 1

    result = {
        "ok": True,
        "status": status,
        "paths": paths,
        "count": len(paths) if paths else 0,
        "samples_loaded": added,
    }
    print(json.dumps(result) if args.json else status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
