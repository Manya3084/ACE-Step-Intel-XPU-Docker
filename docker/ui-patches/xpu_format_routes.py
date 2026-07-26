"""Standalone format routes — use /xpu/format_input to avoid Gradio route clashes.

Host curl to /format_input may hit our handler while Express sometimes hit a
Gradio/FastAPI stub that expects query param 'request' (422). Register a
dedicated /xpu/format_* path and keep legacy aliases.
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


def _has_lm_weights(handler) -> bool:
    if handler is None:
        return False
    for attr in ("llm", "model", "_model", "lm_model", "pytorch_model"):
        if getattr(handler, attr, None) is not None:
            return True
    if getattr(handler, "_lm_full_model_path", None):
        return True
    cfg = getattr(handler, "_last_initialize_config", None) or {}
    return bool(cfg.get("lm_model_path"))


def _is_llm_ready(handler) -> bool:
    if handler is None:
        return False
    if bool(getattr(handler, "llm_initialized", False)):
        return True
    if _has_lm_weights(handler):
        try:
            handler.llm_initialized = True
        except Exception:
            pass
        return True
    return False


def register_format_routes(demo, llm_handler) -> None:
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
                        return
                    except Exception:
                        pass
            try:
                model.to("cpu")
            except Exception:
                pass
        except Exception:
            pass

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
            return None, "LLM handler is None"
        if _is_llm_ready(handler):
            return handler, None
        model_path = os.environ.get("ACESTEP_LM_MODEL_PATH") or "acestep-5Hz-lm-1.7B"
        checkpoint_dir = os.environ.get("ACESTEP_CHECKPOINTS_DIR") or "/app/checkpoints"
        backend = (os.environ.get("ACESTEP_LLM_BACKEND") or "pt").strip().lower()
        device = (
            os.environ.get("ACESTEP_LM_DEVICE")
            or os.environ.get("PYTORCH_DEVICE")
            or "xpu"
        ).strip()
        offload = _env_bool("ACESTEP_LM_OFFLOAD_TO_CPU", True)
        init = getattr(handler, "initialize", None)
        if callable(init):
            try:
                status, ok = init(
                    checkpoint_dir=checkpoint_dir,
                    lm_model_path=model_path,
                    backend=backend,
                    device=device,
                    offload_to_cpu=offload,
                    dtype=None,
                )
                if ok:
                    try:
                        handler.llm_initialized = True
                    except Exception:
                        pass
                    return handler, None
                return handler, f"initialize failed: {status}"
            except Exception as exc:
                return handler, f"initialize error: {exc}"
        return handler, "LLM not initialized"

    async def format_input_endpoint(req: Request):
        """JSON body: prompt/caption, lyrics, temperature, param_obj."""
        try:
            body = await req.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        prompt = body.get("prompt") or body.get("caption") or ""
        lyrics = body.get("lyrics") or ""
        try:
            temperature = float(body.get("temperature", 0.85))
        except Exception:
            temperature = 0.85

        if not str(prompt).strip():
            return {
                "data": None,
                "code": 400,
                "error": "Caption/style is required for Format",
                "timestamp": int(time.time() * 1000),
                "extra": None,
            }

        param_obj = body.get("param_obj", {}) or {}
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
            print(
                f"[XPU-format] caption={str(prompt)[:80]!r} "
                f"llm_initialized={getattr(handler, 'llm_initialized', None)} "
                f"has_weights={_has_lm_weights(handler)}"
            )
            handler, err = _ensure_llm_ready(handler)
            if err:
                raise RuntimeError(err)
            try:
                handler.llm_initialized = True
            except Exception:
                pass
            _empty_cache("(before format)")
            _park_dit_cpu()
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
            print(f"[XPU-format] error: {exc}")
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
        print(f"[XPU-format] OK caption={str(data.get('caption') or '')[:60]!r}")
        return {
            "data": data,
            "code": 200,
            "error": None,
            "timestamp": int(time.time() * 1000),
            "extra": None,
        }

    paths = (
        "/xpu/format_input",
        "/xpu/format_lyrics",
        "/format_input",
        "/format_lyrics",
    )
    try:
        kept = []
        for r in list(app.router.routes):
            path = getattr(r, "path", None)
            if path in paths:
                print(f"[XPU-format] removing old route {path}")
                continue
            kept.append(r)
        app.router.routes = kept
    except Exception as exc:
        print(f"[XPU-format] route cleanup: {exc}")

    for path in paths:
        app.add_api_route(path, format_input_endpoint, methods=["POST"])
    print(f"[XPU] Registered format routes: {', '.join(paths)}")
