"""Standalone /format_input + /format_lyrics with A770 headroom + LM ensure.

ace-step-ui Format → POST /format_input. "LLM not initialized" often means
llm_handler.llm_initialized stayed False after a successful live LM switch
(weights loaded, flag not set). We force-mark ready when the model object
exists, and re-resolve the handler from app.state on every request.
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
    # path recorded after successful init
    if getattr(handler, "_lm_full_model_path", None):
        return True
    cfg = getattr(handler, "_last_initialize_config", None) or {}
    if cfg.get("lm_model_path"):
        return True
    return False


def _is_llm_ready(handler) -> bool:
    if handler is None:
        return False
    if bool(getattr(handler, "llm_initialized", False)):
        return True
    # Weights present but flag stuck False (live-switch race)
    if _has_lm_weights(handler):
        try:
            handler.llm_initialized = True
            print("[XPU-format] forced llm_initialized=True (weights present)")
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
                "LLM handler is None — wait until Auto-init finishes, "
                "then try Format again"
            )
        if _is_llm_ready(handler):
            return handler, None

        model_path = os.environ.get("ACESTEP_LM_MODEL_PATH") or "acestep-5Hz-lm-1.7B"
        checkpoint_dir = os.environ.get("ACESTEP_CHECKPOINTS_DIR") or "/app/checkpoints"
        backend = (os.environ.get("ACESTEP_LLM_BACKEND") or "pt").strip().lower()
        device = (os.environ.get("ACESTEP_LM_DEVICE") or os.environ.get("PYTORCH_DEVICE") or "xpu").strip()
        offload = _env_bool("ACESTEP_LM_OFFLOAD_TO_CPU", True)

        init = getattr(handler, "initialize", None)
        if callable(init):
            try:
                print(
                    f"[XPU-format] LM not ready — initialize("
                    f"path={model_path}, backend={backend}, device={device}, offload={offload})"
                )
                status, ok = init(
                    checkpoint_dir=checkpoint_dir,
                    lm_model_path=model_path,
                    backend=backend,
                    device=device,
                    offload_to_cpu=offload,
                    dtype=None,
                )
                print(f"[XPU-format] initialize → ok={ok} status={status!r}")
                if ok:
                    try:
                        handler.llm_initialized = True
                    except Exception:
                        pass
                    st = getattr(app, "state", None)
                    if st is not None:
                        try:
                            st._llm_initialized = True
                            st._llm_init_error = None
                        except Exception:
                            pass
                    return handler, None
            except TypeError as te:
                print(f"[XPU-format] initialize signature mismatch: {te}")
                try:
                    init()
                    if _is_llm_ready(handler):
                        return handler, None
                except Exception as exc:
                    print(f"[XPU-format] initialize() failed: {exc}")
            except Exception as exc:
                print(f"[XPU-format] initialize failed: {exc}")

        if not _is_llm_ready(handler):
            return handler, (
                "LLM not initialized (flag=False, no weights). "
                "Wait for '5Hz LM initialized' in logs, or switch LM once in UI."
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
        except Exception:
            pass

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

        if not str(prompt).strip():
            return {
                "data": None,
                "code": 400,
                "error": "Caption/style is required for Format",
                "timestamp": int(time.time() * 1000),
                "extra": None,
            }

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
            print(
                f"[XPU-format] handler={type(handler).__name__ if handler else None} "
                f"llm_initialized={getattr(handler, 'llm_initialized', None)} "
                f"has_weights={_has_lm_weights(handler)}"
            )
            handler, err = _ensure_llm_ready(handler)
            if err:
                raise RuntimeError(err)
            # format_sample checks llm_initialized strictly — force True once more
            try:
                handler.llm_initialized = True
            except Exception:
                pass
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

    # Drop prior registrations (ours + upstream APIRouter copies)
    try:
        kept = []
        for r in list(app.router.routes):
            path = getattr(r, "path", None)
            if path in ("/format_input", "/format_lyrics"):
                print(f"[XPU-format] removing route {path} {type(r).__name__}")
                continue
            kept.append(r)
        app.router.routes = kept
    except Exception as exc:
        print(f"[XPU-format] route cleanup warning: {exc}")

    app.add_api_route("/format_input", format_input_endpoint, methods=["POST"])
    app.add_api_route("/format_lyrics", format_input_endpoint, methods=["POST"])
    print("[XPU] Registered /format_input and /format_lyrics (force-ready + headroom)")
