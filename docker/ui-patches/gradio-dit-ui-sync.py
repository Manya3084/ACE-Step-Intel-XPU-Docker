#!/usr/bin/env python3
"""Keep Gradio DiT control bounds compatible with every 1.5 / 1.5XL variant.

Problem:
  Stack boots on turbo → Gradio Slider inference_steps maximum=20.
  Live /v1/init to base/XL does not refresh Gradio component bounds.
  ace-step-ui then POSTs steps=40–50 → Gradio preprocess rejects:
    Value N is greater than maximum value 20.

Fix:
  1) model_config.get_ui_control_config: turbo also gets maximum=200
     (default value stays 8 for turbo; base/sft stay 32/50).
  2) Always expose guidance / ADG / cfg interval components in the Gradio
     graph so API clients can send those args without bound/visibility
     mismatches (handler still respects model-type behaviour).
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[XPU-DIT-UI-SYNC]"


def patch_model_config(path: Path) -> bool:
    text = path.read_text()
    if MARKER in text and '"inference_steps_maximum": 200' in text:
        if '"inference_steps_maximum": 20' in text and "is_turbo" in text:
            pass
        else:
            print(f"Already synced: {path}")
            return False

    changed = False

    old_turbo = '''    if is_turbo:
        return {
            "inference_steps_value": 8,
            "inference_steps_maximum": 20,
            "inference_steps_minimum": 1,
            "guidance_scale_visible": False,
            "use_adg_visible": False,
            "shift_value": 3.0,
            "shift_visible": True,
            "dcw_enabled_value": True,
            "cfg_interval_start_visible": False,
            "cfg_interval_end_visible": False,
            "task_type_choices": task_choices,
            "generation_mode_choices": mode_choices,
        }'''

    new_turbo = f'''    if is_turbo:
        # {MARKER}: max must match base/XL so live-switch + ace-step-ui
        # can send 32–50 steps without Gradio Slider preprocess rejecting.
        # Default value stays 8 (turbo). Visibility left open for API clients.
        return {{
            "inference_steps_value": 8,
            "inference_steps_maximum": 200,
            "inference_steps_minimum": 1,
            "guidance_scale_visible": True,
            "use_adg_visible": True,
            "shift_value": 3.0,
            "shift_visible": True,
            "dcw_enabled_value": True,
            "cfg_interval_start_visible": True,
            "cfg_interval_end_visible": True,
            "task_type_choices": task_choices,
            "generation_mode_choices": mode_choices,
        }}'''

    if old_turbo in text:
        text = text.replace(old_turbo, new_turbo, 1)
        changed = True
        print("OK turbo inference_steps_maximum 20 → 200 + API-visible controls")
    elif '"inference_steps_maximum": 20' in text:
        text = text.replace(
            '"inference_steps_maximum": 20',
            f'"inference_steps_maximum": 200,  # {MARKER}',
            1,
        )
        changed = True
        print("OK turbo max 20 → 200 (loose replace)")
    else:
        print("WARN: turbo max=20 block not found (may already be patched)", file=sys.stderr)

    if '"inference_steps_maximum": 200' not in text:
        print("WARN: base max 200 not present", file=sys.stderr)

    if changed:
        path.write_text(text)
        print(f"Wrote {path}")
    return changed


def main() -> None:
    paths = list(Path("/app").rglob("model_config.py"))
    paths = [p for p in paths if "gradio" in str(p) and "generation" in str(p)]
    if not paths:
        paths = list(Path(".").rglob("acestep/ui/gradio/events/generation/model_config.py"))
    if not paths:
        print("model_config.py not found", file=sys.stderr)
        sys.exit(1)

    n = 0
    for p in paths:
        if patch_model_config(p):
            n += 1
    print(f"gradio-dit-ui-sync: {n} file(s) updated")


if __name__ == "__main__":
    main()
