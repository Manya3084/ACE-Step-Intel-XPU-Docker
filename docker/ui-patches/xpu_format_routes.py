"""Standalone /format_input + /format_lyrics with A770 headroom + LM ensure.

Imported by acestep_v15_pipeline after setup_api_routes.

ace-step-ui Format calls POST /format_input. Failures that surface as
"LLM not initialized" / "LLM may not be available" usually mean the
closure captured a None/unready handler. We re-resolve from app.state and
attempt initialize() before format_sample.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import time


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


def _is_llm_ready(handler) -> bool:
    if handler is None:
        return False
    return bool(
        getattr(handler, "llm_initialized", False)
        or getattr(handler, "is_initialized", False)
        or getattr(handler, "initialized", False)
    )


def register_format_routes(demo, llm_handler) -> None:
    """Register POST /format_input and /format_lyrics on the Gradio FastAPI app."""
    try:
        from fastapi import Request
    except Exception as exc:
        print(f"[XPU] format routes: fastapi missing ({exc})")
        return

    try:
        app = demo.app
    except Exception as exc:
        print(f"[XPU] format routes: no demo.app ({exc})")
        return

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
        st = getattr(app, "state", None)
        if st is not None:
            for attr in ("llm_handler", "_llm_handler", "lm_handler"):
                h = getattr(st, attr, None)
                if h is not None:
                    return h
        return llm_handler

    def _ensure_llm_ready(handler):
        if handler is None:
            return None, (
                "LLM handler is None — wait until Auto-init finishes "
                "(LM line in startup log), then try Format again"
            )
        if _is_llm_ready(handler):
            return handler, None

        model_path = os.environ.get("ACESTEP_LM_MODEL_PATH") or "acestep-5Hz-lm-1.7B"
        for name in ("initialize", "init_llm", "ensure_initialized", "load_model"):
            fn = getattr(handler, name, None)
            if not callable(fn):
                continue
            try:
                print(f"[XPU-format] LM not ready — calling handler.{name}()")
                try:
                    fn()
                except TypeError:
                    try:
                        fn(lm_model_path=model_path)
                    except TypeError:
                        fn(model_path)
                if _is_llm_ready(handler):
                    print(f"[XPU-format] LM ready after {name}()")
                    return handler, None
            except Exception as exc:
                print(f"[XPU-format] handler.{name}() failed: {exc}")

        if not _is_llm_ready(handler):
            return handler, (
                "LLM not initialized — wait for LM load on startup, "
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
        time_signature = param_obj.get("time_signature") or body.get("time_signature") or ""
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
                return format_sample(
                    llm_handler=handler,
                    caption=prompt,
                    lyrics=lyrics,
                    user_metadata=user_metadata or None,
                    temperature=temperature,
                    use_constrained_decoding=True,
                )
            finally:
                _empty_cache("(after format)")

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
    print("[XPU] Registered /format_input and /format_lyrics (LM ensure + RAM headroom)")
