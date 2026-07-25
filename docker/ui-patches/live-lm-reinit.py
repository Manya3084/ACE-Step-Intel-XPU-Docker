#!/usr/bin/env python3
"""Patch Gradio api_routes.py for live LM re-init via POST /v1/init.

Upstream Gradio /v1/init only switches DiT. This adds LM switch support:

  POST /v1/init
  {
    "model": "acestep-v15-turbo",          # optional DiT
    "init_llm": true,
    "lm_model_path": "acestep-5Hz-lm-4B"  # or 1.7B / 0.6B
  }

  # LM-only switch (keep current DiT):
  { "init_llm": true, "lm_model_path": "acestep-5Hz-lm-4B" }

Honors ACESTEP_LM_OFFLOAD_TO_CPU / ACESTEP_LM_DEVICE / ACESTEP_ALLOW_4B_LM
so 4B can live on system RAM on A770 + 128GB hosts.

IMPORTANT: path helpers MUST NOT embed backslash-escaped string literals
in the generated code — previous versions produced:
    rstrip("/\\")  # SyntaxError: unterminated string literal
Use chr(92) / .replace so the written source is always valid Python.

Also: never emit multi-line f-strings for the "Download first" error
message — older images left an unterminated f"Download first, e.g.:
literal. Use .format() instead.
"""
from __future__ import annotations

import re
from pathlib import Path

MARKER = "# [XPU-LIVE-LM-REINIT]"

# NOTE: HELPERS is written into api_routes.py. Never put \\ inside a
# normal "..." string in this block — use chr(92) instead.
# The RuntimeError message uses .format() so the generated source cannot
# contain an unterminated multi-line f-string.
HELPERS = '''
# [XPU-LIVE-LM-REINIT]
_KNOWN_LM_MODELS = (
    "acestep-5Hz-lm-0.6B",
    "acestep-5Hz-lm-1.7B",
    "acestep-5Hz-lm-4B",
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _basename_ckpt(path) -> str:
    """Basename of a checkpoint path; works for both / and \\ separators."""
    # chr(92) == backslash — avoids writing rstrip("/\\") which breaks Python
    return os.path.basename(str(path).replace(chr(92), "/").rstrip("/"))


def _current_lm_name(llm_handler) -> Optional[str]:
    """Return the currently loaded 5Hz LM checkpoint name, if any."""
    if llm_handler is None or not getattr(llm_handler, "llm_initialized", False):
        return None
    cfg = getattr(llm_handler, "_last_initialize_config", None) or {}
    path = cfg.get("lm_model_path") or ""
    if path:
        return _basename_ckpt(path)
    full = getattr(llm_handler, "_lm_full_model_path", None) or ""
    if full:
        return _basename_ckpt(full)
    return None


def _collect_available_lm_names(llm_handler) -> List[str]:
    names = set(_KNOWN_LM_MODELS)
    if llm_handler is not None and hasattr(llm_handler, "get_available_5hz_lm_models"):
        try:
            names.update(llm_handler.get_available_5hz_lm_models() or [])
        except Exception as exc:
            logger.warning(f"[v1/models] get_available_5hz_lm_models failed: {exc}")
    # Also scan checkpoints dir directly
    try:
        ckpt = os.path.join(_get_project_root(), "checkpoints")
        if os.path.isdir(ckpt):
            for entry in os.listdir(ckpt):
                if entry.startswith("acestep-5Hz-lm-") and os.path.isdir(os.path.join(ckpt, entry)):
                    names.add(entry)
    except Exception:
        pass
    current = _current_lm_name(llm_handler)
    if current:
        names.add(current)
    return sorted(names)


def _switch_lm_model_sync(llm_handler, lm_model_path: str) -> Dict[str, Any]:
    """Blocking LM switch used by POST /v1/init (run in a worker thread).

    Unloads the previous LM (if any), then initializes the requested checkpoint
    with ACESTEP_LM_OFFLOAD_TO_CPU / ACESTEP_LM_DEVICE for RAM-backed 4B.
    """
    if llm_handler is None:
        raise RuntimeError("LLM handler is not available")

    lm_model_path = (lm_model_path or "").strip()
    if not lm_model_path:
        raise RuntimeError("lm_model_path is required when init_llm=true")

    # Normalize bare names like "4B" / "1.7B"
    if not lm_model_path.startswith("acestep-5Hz-lm-"):
        if lm_model_path.upper().endswith("B") and lm_model_path[0].isdigit():
            lm_model_path = f"acestep-5Hz-lm-{lm_model_path}"

    current = _current_lm_name(llm_handler)
    if current == lm_model_path and getattr(llm_handler, "llm_initialized", False):
        _clear_accelerator_cache("(LM already loaded, cache only)")
        return {
            "message": f"LM '{lm_model_path}' already loaded",
            "loaded_lm_model": lm_model_path,
            "lm_switched": False,
            "lm_offload_to_cpu": bool(getattr(llm_handler, "offload_to_cpu", False)),
            "lm_device": str(getattr(llm_handler, "device", "?")),
        }

    project_root = _get_project_root()
    checkpoint_dir = os.path.join(project_root, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    full_path = os.path.join(checkpoint_dir, lm_model_path)
    if not os.path.isdir(full_path):
        # Attempt download via model_downloader if available
        try:
            from acestep.model_downloader import ensure_model_downloaded
            ensure_model_downloaded(lm_model_path, checkpoint_dir)
        except Exception as dl_exc:
            logger.warning(f"[v1/init] LM download helper failed: {dl_exc}")
        if not os.path.isdir(full_path):
            # Use .format() — never multi-line f-strings that can leave an
            # unterminated literal in older / partially-applied patches.
            msg = (
                "LM checkpoint not found at {}. "
                "Download first, e.g.:\\n"
                "  docker exec acestep-xpu bash -c '. /app/.venv/bin/activate && "
                "huggingface-cli download ACE-Step/{} "
                "--local-dir /app/checkpoints/{}'"
            ).format(full_path, lm_model_path, lm_model_path)
            raise RuntimeError(msg)

    backend = (
        os.environ.get("ACESTEP_LLM_BACKEND")
        or os.environ.get("ACESTEP_LM_BACKEND")
        or "pt"
    ).strip().lower()
    if backend not in ("pt", "vllm", "mlx"):
        backend = "pt"

    # Prefer dedicated LM device / offload env (matches lm-ram-offload.py)
    lm_device = (os.environ.get("ACESTEP_LM_DEVICE") or "").strip() or (
        os.environ.get("ACESTEP_DEVICE")
        or os.environ.get("PYTORCH_DEVICE")
        or "xpu"
    )
    if _env_bool("ACESTEP_LM_OFFLOAD_TO_CPU", True) or lm_device.lower() == "cpu":
        lm_offload = True
        if lm_device.lower() == "cpu":
            pass  # full CPU path
    else:
        lm_offload = _env_bool("ACESTEP_OFFLOAD_TO_CPU", True)

    logger.info(
        f"[v1/init] Switching LM: {current!r} -> {lm_model_path!r} "
        f"(backend={backend}, device={lm_device}, offload_to_cpu={lm_offload})"
    )
    _clear_accelerator_cache("(before LM switch)")

    # Release previous weights so 4B can claim RAM/VRAM cleanly
    try:
        if hasattr(llm_handler, "unload"):
            llm_handler.unload()
    except Exception as unload_exc:
        logger.warning(f"[v1/init] LM unload warning: {unload_exc}")

    status, ok = llm_handler.initialize(
        checkpoint_dir=checkpoint_dir,
        lm_model_path=lm_model_path,
        backend=backend,
        device=lm_device,
        offload_to_cpu=lm_offload,
        dtype=None,
    )
    if not ok:
        raise RuntimeError(status or f"Failed to initialize LM '{lm_model_path}'")

    # Keep env in sync so subsequent lazy paths see the new default
    os.environ["ACESTEP_LM_MODEL_PATH"] = lm_model_path
    os.environ["ACESTEP_INIT_LLM"] = "true"

    _clear_accelerator_cache("(after LM switch)")
    loaded = _current_lm_name(llm_handler) or lm_model_path
    logger.info(f"[v1/init] LM loaded: {loaded}")
    return {
        "message": status or f"LM '{loaded}' initialized",
        "loaded_lm_model": loaded,
        "lm_switched": True,
        "lm_offload_to_cpu": lm_offload,
        "lm_device": lm_device,
    }
'''

NEW_LIST_MODELS = '''
@router.get("/v1/models")
async def list_models(request: Request, _: None = Depends(verify_api_key)):
    """List available DiT + LM models and currently loaded ones."""
    dit_handler = getattr(request.app.state, "dit_handler", None)
    llm_handler = getattr(request.app.state, "llm_handler", None)
    current = _current_dit_name(dit_handler)
    available = _collect_available_dit_names(dit_handler)

    models = [
        {
            "name": name,
            "is_default": bool(current and name == current),
            "is_loaded": bool(current and name == current and dit_handler and dit_handler.model is not None),
        }
        for name in available
    ]
    models.sort(key=lambda m: (not m["is_loaded"], m["name"]))

    loaded_lm = _current_lm_name(llm_handler)
    lm_models = [
        {
            "name": name,
            "is_loaded": bool(loaded_lm and name == loaded_lm),
        }
        for name in _collect_available_lm_names(llm_handler)
    ]

    return _wrap_response({
        "models": models,
        "default_model": current,
        "lm_models": lm_models,
        "loaded_lm_model": loaded_lm,
        "llm_initialized": bool(llm_handler and getattr(llm_handler, "llm_initialized", False)),
    })
'''

NEW_INIT = '''
@router.post("/v1/init")
async def init_model(request: Request, authorization: Optional[str] = Header(None)):
    """Live-switch DiT and/or 5Hz LM without container restart.

    Body JSON examples:
      { "model": "acestep-v15-xl-turbo" }
      { "init_llm": true, "lm_model_path": "acestep-5Hz-lm-4B" }
      { "model": "acestep-v15-turbo", "init_llm": true, "lm_model_path": "acestep-5Hz-lm-4B" }

    DiT always uses dual CPU offload on Arc 16GB.
    LM honors ACESTEP_LM_OFFLOAD_TO_CPU / ACESTEP_LM_DEVICE for RAM path.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    if "json" in content_type:
        body = await request.json()
    else:
        try:
            form = await request.form()
            body = {k: v for k, v in form.items()}
        except Exception:
            body = {}

    verify_token_from_request(body, authorization)

    model_name = (
        body.get("model")
        or body.get("dit_model")
        or body.get("config_path")
        or ""
    )
    model_name = str(model_name).strip()

    init_llm_raw = body.get("init_llm", False)
    if isinstance(init_llm_raw, str):
        init_llm = init_llm_raw.strip().lower() in ("1", "true", "yes", "y", "on")
    else:
        init_llm = bool(init_llm_raw)

    lm_model_path = (
        body.get("lm_model_path")
        or body.get("lm_model")
        or body.get("llm_model")
        or ""
    )
    lm_model_path = str(lm_model_path).strip()
    if init_llm and not lm_model_path:
        lm_model_path = (os.environ.get("ACESTEP_LM_MODEL_PATH") or "acestep-5Hz-lm-1.7B").strip()

    if not model_name and not init_llm:
        return _wrap_response(
            None,
            code=400,
            error="Provide model (DiT) and/or init_llm=true with lm_model_path",
        )

    dit_handler = getattr(request.app.state, "dit_handler", None)
    llm_handler = getattr(request.app.state, "llm_handler", None)

    if model_name and dit_handler is None:
        return _wrap_response(None, code=500, error="DiT handler not available")
    if init_llm and llm_handler is None:
        return _wrap_response(None, code=500, error="LLM handler not available")

    if not _init_lock.acquire(blocking=False):
        return _wrap_response(
            None,
            code=409,
            error="Another model switch is already in progress; try again shortly",
        )

    try:
        result: Dict[str, Any] = {}

        if model_name:
            dit_result = await asyncio.to_thread(_switch_dit_model_sync, dit_handler, model_name)
            result.update(dit_result)

        if init_llm:
            lm_result = await asyncio.to_thread(_switch_lm_model_sync, llm_handler, lm_model_path)
            # Avoid clobbering DiT message; nest LM fields
            result["lm_message"] = lm_result.get("message")
            result["loaded_lm_model"] = lm_result.get("loaded_lm_model")
            result["lm_switched"] = lm_result.get("lm_switched")
            result["lm_offload_to_cpu"] = lm_result.get("lm_offload_to_cpu")
            result["lm_device"] = lm_result.get("lm_device")
            if not model_name:
                result["message"] = lm_result.get("message")
                result["switched"] = lm_result.get("lm_switched")

        models_payload = (await list_models(request, None))["data"]  # type: ignore[index]
        if isinstance(models_payload, dict):
            result["models"] = models_payload.get("models")
            result["lm_models"] = models_payload.get("lm_models")
            result["default_model"] = result.get("loaded_model") or models_payload.get("default_model")
            result["llm_initialized"] = models_payload.get("llm_initialized")
            if "loaded_lm_model" not in result:
                result["loaded_lm_model"] = models_payload.get("loaded_lm_model")

        return _wrap_response(result)
    except Exception as exc:
        logger.exception(f"[v1/init] failed model={model_name!r} lm={lm_model_path!r}")
        return _wrap_response(None, code=500, error=str(exc))
    finally:
        _init_lock.release()
'''


def _replace_function(text: str, decorator_line: str, new_block: str) -> str:
    """Replace a FastAPI route function starting at decorator_line through next top-level @router."""
    start = text.find(decorator_line)
    if start < 0:
        raise SystemExit(f"Could not find route starting with: {decorator_line!r}")
    # Find next @router. after this function
    rest = text[start + len(decorator_line) :]
    next_router = rest.find("\n@router.")
    if next_router < 0:
        raise SystemExit(f"Could not find end of route after {decorator_line!r}")
    end = start + len(decorator_line) + next_router
    return text[:start] + new_block.strip() + "\n" + text[end:]


def _repair_broken_rstrip(text: str) -> str:
    """Fix the classic unterminated-string bug from the previous patch version.

    Broken forms seen in the wild:
      .rstrip("/\\")
      .rstrip("/\\\\")   # sometimes partially escaped
    """
    # Match any rstrip that tries to strip both / and backslash in one literal
    pattern = re.compile(
        r'os\.path\.basename\(str\(([^)]+)\)\.rstrip\("[^"\\]*(?:\\.[^"\\]*)*"\)\)'
    )

    def _repl(m: re.Match) -> str:
        expr = m.group(1)
        return f'os.path.basename(str({expr}).replace(chr(92), "/").rstrip("/"))'

    fixed, n = pattern.subn(_repl, text)
    if n:
        print(f"Repaired {n} broken rstrip/basename expression(s)")
    return fixed


def _strip_old_helpers(text: str) -> str:
    """Remove a previously injected [XPU-LIVE-LM-REINIT] block so we can re-apply cleanly."""
    if MARKER not in text:
        return text
    # From the marker comment through the line before "router = APIRouter()"
    start = text.find(MARKER)
    if start < 0:
        return text
    # Prefer to cut from the blank line before the marker if present
    while start > 0 and text[start - 1] in "\r\n":
        start -= 1
    anchor = "router = APIRouter()"
    end = text.find(anchor, start)
    if end < 0:
        return text
    print("Stripping previous [XPU-LIVE-LM-REINIT] helper block for clean re-apply")
    return text[:start] + "\n" + text[end:]


def _helpers_healthy(text: str) -> bool:
    """True only if the live-LM helpers look complete *and* the file parses."""
    if MARKER not in text:
        return False
    if "_basename_ckpt" not in text or "_switch_lm_model_sync" not in text:
        return False
    # Known broken form left by an earlier multi-line f-string
    if 'f"Download first, e.g.:' in text:
        # Accept only the properly closed single-line form (or the .format form)
        if 'f"Download first, e.g.:\n"' not in text and 'f"Download first, e.g.:\\n"' not in text:
            print("Detected broken unterminated 'Download first' f-string — will re-apply")
            return False
    try:
        compile(text, "<api_routes.py>", "exec")
    except SyntaxError as exc:
        print(f"api_routes.py still has SyntaxError ({exc}) — will re-apply helpers")
        return False
    return True


def main() -> None:
    paths = list(Path("/app").rglob("api_routes.py"))
    paths = [p for p in paths if "gradio" in str(p) and "api" in str(p)]
    if not paths:
        # Dev / host checkout path
        paths = list(Path(".").rglob("acestep/ui/gradio/api/api_routes.py"))
    if not paths:
        raise SystemExit("api_routes.py not found")

    for path in paths:
        text = path.read_text()

        # Always repair known broken rstrip forms first (even if already marked)
        text = _repair_broken_rstrip(text)

        if _helpers_healthy(text):
            path.write_text(text)
            print(f"Already patched (helpers OK): {path}")
            continue

        # Remove a partial / broken previous injection so we can re-insert cleanly
        text = _strip_old_helpers(text)

        anchor = "router = APIRouter()"
        if anchor not in text:
            raise SystemExit(f"'{anchor}' not found in {path}")
        if "_switch_dit_model_sync" not in text:
            raise SystemExit("_switch_dit_model_sync not found — apply DiT /v1/init patch first")

        text = text.replace(anchor, HELPERS.rstrip() + "\n\n" + anchor, 1)

        text = _replace_function(
            text,
            '@router.get("/v1/models")',
            NEW_LIST_MODELS,
        )
        text = _replace_function(
            text,
            '@router.post("/v1/init")',
            NEW_INIT,
        )

        # Final sanity check before writing
        try:
            compile(text, str(path), "exec")
        except SyntaxError as exc:
            raise SystemExit(f"Patched api_routes.py is still invalid: {exc}") from exc

        path.write_text(text)
        print(f"Patched live LM re-init into {path}")

    print("live-lm-reinit patch complete")


if __name__ == "__main__":
    main()
