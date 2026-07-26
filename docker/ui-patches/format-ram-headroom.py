#!/usr/bin/env python3
"""/format_input + /format_lyrics with XPU headroom and LM ensure-init.

ace-step-ui Format button hits POST /format_input. Upstream often returns
"LLM not initialized" when the handler closed over a stale/None llm or
llm_initialized is False after offload/switch. This route resolves the
live handler from app.state and initializes if needed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

NEW_HELPER = r'''
def _xpu_register_format_input(demo, llm_handler):
    """POST /format_input + /format_lyrics with A770 RAM/VRAM headroom + LM ensure."""
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

    def _resolve_llm():
        """Prefer live app.state handler over closure (survives re-init)."""
        st = getattr(app, "state", None)
        for attr in ("llm_handler", "_llm_handler", "lm_handler"):
            h = getattr(st, attr, None) if st is not None else None
            if h is not None:
                return h
        return llm_handler

    def _ensure_llm_ready(handler):
        if handler is None:
            return None, "LLM handler is None — start acestep-xpu with init_llm / ACESTEP_LM_MODEL_PATH"
        initialized = bool(
            getattr(handler, "llm_initialized", False)
            or getattr(handler, "is_initialized", False)
            or getattr(handler, "initialized", False)
        )
        if initialized:
            return handler, None
        # Try common init entry points
        for name in ("initialize", "init_llm", "load_model", "ensure_initialized"):
            fn = getattr(handler, name, None)
            if not callable(fn):
                continue
            try:
                print(f"[XPU-format] calling handler.{name}() to init LM")
                fn()
                initialized = bool(
                    getattr(handler, "llm_initialized", False)
                    or getattr(handler, "is_initialized", False)
                    or getattr(handler, "initialized", False)
                )
                if initialized:
                    return handler, None
            except TypeError:
                # maybe needs kwargs — try with env model path
                try:
                    mp = os.environ.get("ACESTEP_LM_MODEL_PATH") or "acestep-5Hz-lm-1.7B"
                    fn(lm_model_path=mp)
                    return handler, None
                except Exception as exc:
                    print(f"[XPU-format] {name}() failed: {exc}")
            except Exception as exc:
                print(f"[XPU-format] {name}() failed: {exc}")
        if not (
            getattr(handler, "llm_initialized", False)
            or getattr(handler, "is_initialized", False)
        ):
            return handler, (
                "LLM not initialized — wait for Auto-init LM to finish, "
                "or switch LM once in the UI, then Format again"
            )
        return handler, None

    def _ensure_lm_offload(handler) -> None:
        if handler is None:
            return
        want = _env_bool("ACESTEP_LM_OFFLOAD_TO_CPU", True) or _env_bool(
            "ACESTEP_OFFLOAD_TO_CPU", True
        )
        if not want:
            return
        try:
            if hasattr(handler, "offload_to_cpu"):
                setattr(handler, "offload_to_cpu", True)
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
            handler = _resolve_llm()
            handler, err = _ensure_llm_ready(handler)
            if err:
                raise RuntimeError(err)
            print("[XPU-format] preparing headroom before format_sample")
            _empty_cache("(before format)")
            _park_dit_cpu()
            _ensure_lm_offload(handler)
            _empty_cache("(after park)")
            from acestep.inference import format_sample

            try:
                result = format_sample(
                    llm_handler=handler,
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
    print("[XPU] Registered /format_input and /format_lyrics (standalone + RAM headroom + LM ensure)")
'''


def _function_end_by_indent(text: str, start: int) -> int:
    nl = text.find("\n", start)
    if nl < 0:
        return len(text)
    i = nl + 1
    n = len(text)
    while i < n:
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
        if line.startswith(" ") or line.startswith("\t"):
            i = line_end
            continue
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
        if "[XPU-format] calling handler" in text or "_ensure_llm_ready" in text:
            # replace whole helper to latest
            pass

        if "def _xpu_register_format_input" in text:
            start = text.find("def _xpu_register_format_input")
            end = _function_end_by_indent(text, start)
            text = text[:start] + NEW_HELPER.strip() + "\n\n" + text[end:]
            path.write_text(text)
            print(f"Replaced _xpu_register_format_input in {path}")
        else:
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
            print(f"Inserted format helper into {path}")

    print("format-ram-headroom patch complete")


if __name__ == "__main__":
    main()
