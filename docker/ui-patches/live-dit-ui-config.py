#!/usr/bin/env python3
"""Attach model-type ui_config to live DiT switch response.

ace-step-ui can use this to align Create-panel defaults with the loaded DiT.

Also repairs a prior bug where return used result_ui without defining it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-DIT-UI-CONFIG]"

HELPER = r'''
def _dit_ui_config_for_model(model_name: str) -> dict:
    """Mirror Gradio model_config.get_ui_control_config for API clients."""
    name = (model_name or "").lower()
    is_turbo = "turbo" in name
    is_sft = "sft" in name and not is_turbo
    is_pure_base = "base" in name and not is_turbo and not is_sft
    if is_turbo:
        return {
            "family": "turbo",
            "inference_steps_value": 8,
            "inference_steps_maximum": 200,
            "inference_steps_minimum": 1,
            "guidance_scale_value": 7.0,
            "guidance_scale_visible": True,
            "use_adg_value": False,  # XPU: ADG unsafe on Arc
            "use_adg_visible": True,
            "shift_value": 3.0,
            "dcw_enabled_value": True,
            "cfg_interval_visible": True,
            "is_turbo": True,
            "is_sft": False,
            "is_pure_base": False,
            "is_xl": "xl" in name,
        }
    steps = 50 if (is_sft or is_pure_base) else 32
    return {
        "family": "sft" if is_sft else ("base" if is_pure_base else "other"),
        "inference_steps_value": steps,
        "inference_steps_maximum": 200,
        "inference_steps_minimum": 1,
        "guidance_scale_value": 7.0,
        "guidance_scale_visible": True,
        "use_adg_value": False,  # XPU: ADG unsafe on Arc
        "use_adg_visible": True,
        "shift_value": 3.0,
        "dcw_enabled_value": False,
        "cfg_interval_visible": True,
        "is_turbo": False,
        "is_sft": is_sft,
        "is_pure_base": is_pure_base,
        "is_xl": "xl" in name,
    }
'''


def _ensure_helper(text: str) -> str:
    if "_dit_ui_config_for_model" in text:
        return text
    anchor = "def _switch_dit_model_sync"
    idx = text.find(anchor)
    if idx < 0:
        return text
    return text[:idx] + f"# {MARKER}\n" + HELPER + "\n" + text[idx:]


def _repair_result_ui(text: str) -> str:
    """Never leave NameError: result_ui — always call helper inline."""
    # Broken prior patch
    text = text.replace(
        '"ui_config": result_ui,',
        '"ui_config": _dit_ui_config_for_model(loaded),  # [XPU-DIT-UI-CONFIG]',
    )
    text = text.replace(
        '"ui_config": result_ui',
        '"ui_config": _dit_ui_config_for_model(loaded)  # [XPU-DIT-UI-CONFIG]',
    )
    # Drop orphan assignment if present
    text = re.sub(
        r"\n\s*result_ui = _dit_ui_config_for_model\(loaded\)[^\n]*",
        "",
        text,
    )
    return text


def _inject_ui_config_on_returns(text: str) -> str:
    """Add ui_config key to switch success / already-loaded returns if missing."""
    if '"ui_config":' in text and "_dit_ui_config_for_model" in text:
        return text

    # Success return (switched True)
    old_ok = '''    return {
        "message": msg,
        "loaded_model": loaded,
        "switched": True,
        "offload_to_cpu": offload_to_cpu,
        "offload_dit_to_cpu": offload_dit_to_cpu,
    }'''
    new_ok = '''    return {
        "message": msg,
        "loaded_model": loaded,
        "switched": True,
        "offload_to_cpu": offload_to_cpu,
        "offload_dit_to_cpu": offload_dit_to_cpu,
        "ui_config": _dit_ui_config_for_model(loaded),
    }'''
    if old_ok in text:
        text = text.replace(old_ok, new_ok, 1)

    old_early = '''        return {
            "message": f"DiT '{model_name}' already loaded",
            "loaded_model": model_name,
            "switched": False,
            "offload_to_cpu": offload_to_cpu,
            "offload_dit_to_cpu": offload_dit_to_cpu,
        }'''
    new_early = '''        return {
            "message": f"DiT '{model_name}' already loaded",
            "loaded_model": model_name,
            "switched": False,
            "offload_to_cpu": offload_to_cpu,
            "offload_dit_to_cpu": offload_dit_to_cpu,
            "ui_config": _dit_ui_config_for_model(model_name),
        }'''
    if old_early in text:
        text = text.replace(old_early, new_early, 1)

    return text


def main() -> None:
    paths = list(Path("/app").rglob("api_routes.py"))
    paths = [p for p in paths if "gradio" in str(p) and "api" in str(p)]
    if not paths:
        paths = list(Path(".").rglob("acestep/ui/gradio/api/api_routes.py"))
    if not paths:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        text = path.read_text()
        if "_switch_dit_model_sync" not in text:
            print(f"live-dit-switch not present in {path}; skip", file=sys.stderr)
            continue

        orig = text
        text = _ensure_helper(text)
        text = _repair_result_ui(text)
        text = _inject_ui_config_on_returns(text)

        if text == orig:
            print(f"No changes needed: {path}")
            continue

        try:
            compile(text, str(path), "exec")
        except SyntaxError as e:
            raise SystemExit(f"Invalid after ui_config patch: {e}") from e

        path.write_text(text)
        print(f"Patched/repaired ui_config in {path}")

    print("live-dit-ui-config complete")


if __name__ == "__main__":
    main()
