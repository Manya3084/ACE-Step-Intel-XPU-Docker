#!/usr/bin/env python3
"""Give /format_input and /format_lyrics the same headroom as generation.

IMPORTANT: When replacing an existing _xpu_register_format_input, end the
function by *indentation* (column-0 content). Never use "next def" as the
end marker — that deleted all imports between a prepended helper and main()
(including get_gpu_config) and crash-looped the container.
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


def _function_end_by_indent(text: str, start: int) -> int:
    """Return index just past a top-level function starting at start.

    A top-level function ends at the first non-empty line that has no indent
    (column 0) after the def line, excluding blank lines and comments that
    may sit between nested blocks — we only stop on real column-0 code.
    """
    # start at the end of the def line
    nl = text.find("\n", start)
    if nl < 0:
        return len(text)
    i = nl + 1
    n = len(text)
    while i < n:
        # find end of this line
        nl = text.find("\n", i)
        if nl < 0:
            line = text[i:]
            line_end = n
        else:
            line = text[i:nl]
            line_end = nl + 1
        stripped = line.lstrip("\r")
        if stripped.strip() == "" or stripped.lstrip().startswith("#"):
            i = line_end
            continue
        # Indented body continues the function
        if line.startswith(" ") or line.startswith("\t"):
            i = line_end
            continue
        # Column-0 content → end of function
        return i
    return n


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
            start = text.find("def _xpu_register_format_input")
            end = _function_end_by_indent(text, start)
            text = text[:start] + NEW_HELPER.strip() + "\n\n" + text[end:]
            path.write_text(text)
            print(f"Replaced _xpu_register_format_input (indent-safe) in {path}")
        else:
            # Prefer insert *after* imports: before first top-level def that is not ours
            m = re.search(r"^(def |class )", text, flags=re.M)
            if m:
                insert_at = m.start()
                text = text[:insert_at] + NEW_HELPER.strip() + "\n\n" + text[insert_at:]
            else:
                text = NEW_HELPER + "\n" + text
            if "_xpu_register_format_input(demo, llm_handler)" not in text:
                pat = re.compile(r"(setup_api_routes\([^\n]*\))")
                mm = pat.search(text)
                if mm:
                    text = pat.sub(
                        mm.group(1)
                        + "\n            _xpu_register_format_input(demo, llm_handler)",
                        text,
                        count=1,
                    )
            path.write_text(text)
            print(f"Inserted format headroom helper into {path}")

    print("format-ram-headroom patch complete")


if __name__ == "__main__":
    main()
