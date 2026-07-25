#!/usr/bin/env python3
"""Give /format_input and /format_lyrics the same headroom as generation.

On Arc A770, Format was loading the LM to XPU while XL DiT still occupied
VRAM, then the HTTP socket dropped (UI: other side closed).

This rewrites _xpu_register_format_input (or injects it) so each Format call:
  1. torch.xpu.empty_cache() + gc
  2. forces llm_handler.offload_to_cpu = True when env says so
  3. best-effort moves DiT weights to CPU for the duration of Format
  4. runs format_sample
  5. empty_cache again
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

NEW_HELPER = r'''
def _xpu_register_format_input(demo, llm_handler):
    """POST /format_input + /format_lyrics with A770 RAM/VRAM headroom."""
    import asyncio
    import gc
    import json
    import os
    import time
    from fastapi import Request

    try:
        app = demo.app
    except Exception as exc:
        print(f"[XPU] format_input: no demo.app ({exc})")
        return

    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")

    def _empty_cache(tag: str = "") -> None:
        try:
            import torch
            if hasattr(torch, "xpu") and torch.xpu.is_available():
                torch.xpu.empty_cache()
                print(f"[XPU-format] torch.xpu.empty_cache() {tag}".strip())
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:
            print(f"[XPU-format] empty_cache warning: {exc}")
        try:
            gc.collect()
        except Exception:
            pass

    def _park_dit_cpu() -> None:
        """Best-effort: free VRAM by parking DiT on CPU during Format."""
        try:
            dit = getattr(getattr(app, "state", None), "dit_handler", None)
            if dit is None:
                return
            model = getattr(dit, "model", None)
            if model is None:
                return
            # Prefer existing offload helpers if present
            for name in ("offload_to_cpu", "_offload_model_to_cpu", "move_to_cpu"):
                fn = getattr(dit, name, None)
                if callable(fn):
                    try:
                        fn()
                        print(f"[XPU-format] DiT parked via dit.{name}()")
                        return
                    except Exception:
                        pass
            try:
                model.to("cpu")
                print("[XPU-format] DiT model.to('cpu')")
            except Exception as exc:
                print(f"[XPU-format] DiT park skipped: {exc}")
        except Exception as exc:
            print(f"[XPU-format] DiT park warning: {exc}")

    def _ensure_lm_offload() -> None:
        if llm_handler is None:
            return
        want = _env_bool("ACESTEP_LM_OFFLOAD_TO_CPU", True) or _env_bool(
            "ACESTEP_OFFLOAD_TO_CPU", True
        )
        if not want:
            return
        try:
            if hasattr(llm_handler, "offload_to_cpu"):
                setattr(llm_handler, "offload_to_cpu", True)
                print("[XPU-format] llm_handler.offload_to_cpu = True")
        except Exception as exc:
            print(f"[XPU-format] LM offload flag warning: {exc}")

    async def format_input_endpoint(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        prompt = body.get("prompt") or body.get("caption") or ""
        lyrics = body.get("lyrics") or ""
        temperature = body.get("temperature", 0.85)
        try:
            temperature = float(temperature)
        except Exception:
            temperature = 0.85

        param_obj = body.get("param_obj", {})
        if isinstance(param_obj, str):
            try:
                param_obj = json.loads(param_obj) if param_obj else {}
            except Exception:
                param_obj = {}
        if not isinstance(param_obj, dict):
            param_obj = {}

        # Also accept flat body fields from ace-step-ui
        user_metadata = {}
        bpm = param_obj.get("bpm") if param_obj.get("bpm") is not None else body.get("bpm")
        duration = (
            param_obj.get("duration")
            if param_obj.get("duration") is not None
            else body.get("duration")
        )
        key_scale = (
            param_obj.get("key")
            or param_obj.get("key_scale")
            or body.get("key_scale")
            or ""
        )
        time_signature = (
            param_obj.get("time_signature") or body.get("time_signature") or ""
        )
        language = param_obj.get("language") or body.get("vocal_language") or ""
        if bpm not in (None, "", 0, "0"):
            try:
                user_metadata["bpm"] = int(bpm)
            except Exception:
                pass
        if duration not in (None, "", 0, "0", -1, "-1"):
            try:
                user_metadata["duration"] = int(float(duration))
            except Exception:
                pass
        if key_scale:
            user_metadata["keyscale"] = str(key_scale)
        if time_signature:
            user_metadata["timesignature"] = str(time_signature)
        if language and language != "unknown":
            user_metadata["language"] = str(language)

        def _run():
            print("[XPU-format] preparing headroom before format_sample")
            _empty_cache("(before format)")
            _park_dit_cpu()
            _ensure_lm_offload()
            _empty_cache("(after park)")
            from acestep.inference import format_sample

            try:
                result = format_sample(
                    llm_handler=llm_handler,
                    caption=prompt,
                    lyrics=lyrics,
                    user_metadata=user_metadata or None,
                    temperature=temperature,
                    use_constrained_decoding=True,
                )
            finally:
                _empty_cache("(after format)")
            return result

        try:
            result = await asyncio.to_thread(_run)
        except Exception as exc:
            print(f"[XPU-format] format_sample error: {exc}")
            _empty_cache("(format error)")
            return {
                "data": None,
                "code": 500,
                "error": f"format_sample error: {exc}",
                "timestamp": int(time.time() * 1000),
                "extra": None,
            }

        if not getattr(result, "success", False):
            err = (
                getattr(result, "error", None)
                or getattr(result, "status_message", None)
                or "format failed"
            )
            return {
                "data": None,
                "code": 500,
                "error": f"format_sample failed: {err}",
                "timestamp": int(time.time() * 1000),
                "extra": None,
            }

        data = {
            "caption": getattr(result, "caption", None) or prompt,
            "lyrics": getattr(result, "lyrics", None) or lyrics,
            "bpm": getattr(result, "bpm", None) or bpm,
            "key_scale": getattr(result, "keyscale", None) or key_scale,
            "time_signature": getattr(result, "timesignature", None) or time_signature,
            "duration": getattr(result, "duration", None) or duration,
            "vocal_language": getattr(result, "language", None) or language or "unknown",
        }
        print("[XPU-format] format_sample completed successfully")
        return {
            "data": data,
            "code": 200,
            "error": None,
            "timestamp": int(time.time() * 1000),
            "extra": None,
        }

    try:
        app.router.routes = [
            r
            for r in app.router.routes
            if getattr(r, "path", None) not in ("/format_input", "/format_lyrics")
        ]
    except Exception:
        pass

    app.add_api_route("/format_input", format_input_endpoint, methods=["POST"])
    app.add_api_route("/format_lyrics", format_input_endpoint, methods=["POST"])
    print("[XPU] Registered working /format_input and /format_lyrics (threaded + RAM headroom)")
'''


def main() -> None:
    paths = list(Path("/app").rglob("acestep_v15_pipeline.py"))
    if not paths:
        paths = list(Path(".").rglob("acestep_v15_pipeline.py"))
    if not paths:
        print("acestep_v15_pipeline.py not found", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        text = path.read_text()
        if "[XPU-format] preparing headroom before format_sample" in text:
            print(f"format headroom already present: {path}")
            continue

        if "def _xpu_register_format_input" in text:
            # Replace existing helper function body through next top-level def after it
            start = text.find("def _xpu_register_format_input")
            # find end: next "\ndef " at column 0 after start, or before class
            rest = text[start + 1 :]
            m = re.search(r"\n(?:def |class )", rest)
            if not m:
                # append-style: replace from def to end of file section before first non-indented after long block
                print("Could not find end of _xpu_register_format_input", file=sys.stderr)
                sys.exit(1)
            end = start + 1 + m.start()
            text = text[:start] + NEW_HELPER.strip() + "\n\n" + text[end:]
            path.write_text(text)
            print(f"Replaced _xpu_register_format_input in {path}")
        else:
            # Insert helper near top after imports-ish, and ensure registration call
            text = NEW_HELPER + "\n" + text
            if "_xpu_register_format_input(demo, llm_handler)" not in text:
                pat = re.compile(r"(setup_api_routes\([^\n]*\))")
                m = pat.search(text)
                if m:
                    text = pat.sub(
                        m.group(1) + "\n            _xpu_register_format_input(demo, llm_handler)",
                        text,
                        count=1,
                    )
            path.write_text(text)
            print(f"Inserted format headroom helper into {path}")

    print("format-ram-headroom patch complete")


if __name__ == "__main__":
    main()
