#!/usr/bin/env python3
"""XPU / high-RAM patch: run 5Hz LM from system RAM and allow 4B on ~16GB Arc.

Upstream hard-downgrades acestep-5Hz-lm-4B → 1.7B whenever VRAM < 20GB,
even with CPU offload. Machines with large system RAM (e.g. 128GB) can keep
LM weights on CPU and only briefly touch XPU during generation.

Env (set in Dockerfile.xpu / compose):
  ACESTEP_LM_OFFLOAD_TO_CPU=true  — LM weights live on CPU; shuttle for generate
  ACESTEP_LM_DEVICE=cpu|xpu|auto  — force LM device (cpu = full RAM path)
  ACESTEP_ALLOW_4B_LM=true        — do not auto-downgrade 4B on tier6a / <20GB
"""
from __future__ import annotations

from pathlib import Path


def _patch_pipeline(path: Path) -> bool:
    text = path.read_text()
    original = text
    marker = "# [XPU-LM-RAM]"
    if marker in text:
        print(f"Already patched: {path}")
        return False

    old_downgrade = '''    # Safety: on 16GB GPUs, prevent selecting LM models that are too large.
    # Even with offloading, a 4B LM (8 GB weights + KV cache) leaves almost no
    # headroom for DiT activations on a 16 GB card.
    if args.lm_model_path and 0 < gpu_memory_gb < VRAM_AUTO_OFFLOAD_THRESHOLD_GB:
        if "4B" in args.lm_model_path:
            # Downgrade to 1.7B if available
            fallback = args.lm_model_path.replace("4B", "1.7B")
            print(
                f"WARNING: 4B LM model is too large for {gpu_memory_gb:.0f}GB GPU. "
                f"Downgrading to 1.7B variant: {fallback}"
            )
            args.lm_model_path = fallback'''

    new_downgrade = '''    # [XPU-LM-RAM] Safety: on <20GB GPUs, default is still to avoid 4B on GPU.
    # Skip the hard downgrade when the operator opts into RAM-backed LM:
    #   ACESTEP_ALLOW_4B_LM=true  OR  ACESTEP_LM_OFFLOAD_TO_CPU=true  OR  ACESTEP_LM_DEVICE=cpu
    _lm_allow_4b = os.environ.get("ACESTEP_ALLOW_4B_LM", "").strip().lower() in (
        "1", "true", "yes", "y", "on",
    )
    _lm_offload_env = os.environ.get("ACESTEP_LM_OFFLOAD_TO_CPU", "").strip().lower()
    _lm_device_env = os.environ.get("ACESTEP_LM_DEVICE", "").strip().lower()
    _lm_ram_path = (
        _lm_allow_4b
        or _lm_offload_env in ("1", "true", "yes", "y", "on")
        or _lm_device_env == "cpu"
    )
    if (
        args.lm_model_path
        and 0 < gpu_memory_gb < VRAM_AUTO_OFFLOAD_THRESHOLD_GB
        and "4B" in args.lm_model_path
        and not _lm_ram_path
    ):
        fallback = args.lm_model_path.replace("4B", "1.7B")
        print(
            f"WARNING: 4B LM model is too large for {gpu_memory_gb:.0f}GB GPU. "
            f"Downgrading to 1.7B variant: {fallback}. "
            f"Set ACESTEP_ALLOW_4B_LM=true + ACESTEP_LM_OFFLOAD_TO_CPU=true to keep 4B on system RAM."
        )
        args.lm_model_path = fallback
    elif (
        args.lm_model_path
        and "4B" in args.lm_model_path
        and _lm_ram_path
        and 0 < gpu_memory_gb < VRAM_AUTO_OFFLOAD_THRESHOLD_GB
    ):
        print(
            f"[XPU-LM-RAM] Keeping 4B LM on {gpu_memory_gb:.0f}GB GPU tier "
            f"(allow_4b / LM offload / LM device=cpu). Expect slower CoT; uses system RAM."
        )'''

    if old_downgrade not in text:
        raise SystemExit(
            f"4B downgrade block not found in {path} — upstream changed; update patch"
        )
    text = text.replace(old_downgrade, new_downgrade, 1)

    old_init = '''                    print(
                        f"Initializing 5Hz LM: {args.lm_model_path} on {args.device}..."
                    )
                    lm_status, lm_success = llm_handler.initialize(
                        checkpoint_dir=checkpoint_dir,
                        lm_model_path=args.lm_model_path,
                        backend=args.backend,
                        device=args.device,
                        offload_to_cpu=args.offload_to_cpu,
                        dtype=None,
                    )'''

    new_init = '''                    # [XPU-LM-RAM] Prefer dedicated LM device / offload env over DiT defaults
                    _lm_device = (
                        os.environ.get("ACESTEP_LM_DEVICE", "").strip()
                        or args.device
                    )
                    _lm_off = os.environ.get("ACESTEP_LM_OFFLOAD_TO_CPU", "").strip().lower()
                    if _lm_off in ("1", "true", "yes", "y", "on"):
                        _lm_offload = True
                    elif _lm_off in ("0", "false", "no", "n", "off"):
                        _lm_offload = False
                    else:
                        _lm_offload = bool(args.offload_to_cpu)
                    if _lm_device.lower() == "cpu":
                        # Full CPU path: still mark offload so handler keeps weights on RAM
                        _lm_offload = True
                    print(
                        f"Initializing 5Hz LM: {args.lm_model_path} on {_lm_device} "
                        f"(offload_to_cpu={_lm_offload})..."
                    )
                    lm_status, lm_success = llm_handler.initialize(
                        checkpoint_dir=checkpoint_dir,
                        lm_model_path=args.lm_model_path,
                        backend=args.backend,
                        device=_lm_device,
                        offload_to_cpu=_lm_offload,
                        dtype=None,
                    )'''

    if old_init not in text:
        raise SystemExit(
            f"LM initialize block not found in {path} — upstream changed; update patch"
        )
    text = text.replace(old_init, new_init, 1)

    if text == original:
        raise SystemExit(f"No changes applied to {path}")
    path.write_text(text)
    print(f"Patched {path}")
    return True


def _patch_gpu_config(path: Path) -> bool:
    text = path.read_text()
    marker = "# [XPU-LM-RAM-TIER6A]"
    if marker in text:
        print(f"Already patched: {path}")
        return False

    insert_before = "def get_lm_model_size(model_path: str) -> str:"
    if insert_before not in text:
        raise SystemExit(f"get_lm_model_size not found in {path}")

    helper = '''def _xpu_expand_lm_models_for_ram(config: "GPUConfig") -> "GPUConfig":
    """[XPU-LM-RAM-TIER6A] Allow 4B LM when operator opts into RAM offload."""
    allow = os.environ.get("ACESTEP_ALLOW_4B_LM", "").strip().lower() in (
        "1", "true", "yes", "y", "on",
    )
    lm_off = os.environ.get("ACESTEP_LM_OFFLOAD_TO_CPU", "").strip().lower() in (
        "1", "true", "yes", "y", "on",
    )
    lm_cpu = os.environ.get("ACESTEP_LM_DEVICE", "").strip().lower() == "cpu"
    if not (allow or lm_off or lm_cpu):
        return config
    four_b = "acestep-5Hz-lm-4B"
    models = list(config.available_lm_models or [])
    if four_b not in models:
        models.append(four_b)
        config.available_lm_models = models
        mem = dict(config.lm_memory_gb or {})
        mem.setdefault("4B", 12)
        config.lm_memory_gb = mem
        logger.info(
            "[XPU-LM-RAM] Expanded available_lm_models to include 4B "
            f"(tier={config.tier}, models={config.available_lm_models})"
        )
    return config


'''
    text = text.replace(insert_before, helper + insert_before, 1)

    if "return _apply_lm_backend_compatibility_overrides(config)" not in text:
        raise SystemExit(f"get_gpu_config return not found in {path}")

    text = text.replace(
        "return _apply_lm_backend_compatibility_overrides(config)",
        "return _xpu_expand_lm_models_for_ram(_apply_lm_backend_compatibility_overrides(config))",
    )

    path.write_text(text)
    print(f"Patched {path}")
    return True


def main() -> None:
    root = Path("/app")
    pipelines = list(root.rglob("acestep_v15_pipeline.py"))
    if not pipelines:
        raise SystemExit("acestep_v15_pipeline.py not found under /app")
    for p in pipelines:
        _patch_pipeline(p)

    gpu_cfgs = [p for p in root.rglob("gpu_config.py") if "acestep" in str(p)]
    if not gpu_cfgs:
        raise SystemExit("acestep/gpu_config.py not found under /app")
    for p in gpu_cfgs:
        _patch_gpu_config(p)

    print("lm-ram-offload patch complete")


if __name__ == "__main__":
    main()
