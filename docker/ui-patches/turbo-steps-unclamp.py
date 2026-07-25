#!/usr/bin/env python3
"""Remove / raise the turbo (dmd_gan) infer_steps hard cap of 8.

Upstream clamps turbo models to 8 steps for speed. Operators who prefer
quality can set ACESTEP_TURBO_MAX_INFER_STEPS (0 or unset = no clamp).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

OLD_BLOCK = '''        if self.config.is_turbo and infer_steps > 8:
            logger.warning(
                "[service_generate] dmd_gan version: infer_steps {} exceeds maximum 8, clamping to 8",
                infer_steps,
            )
            infer_steps = 8'''

NEW_BLOCK = '''        # [XPU-TURBO-STEPS] Optional soft cap via ACESTEP_TURBO_MAX_INFER_STEPS.
        # Unset or 0 = do not clamp (honour user infer_steps). Turbo/dmd_gan was
        # trained for few steps; higher values are slower and may not improve much.
        if self.config.is_turbo:
            import os as _os
            _raw = (_os.environ.get("ACESTEP_TURBO_MAX_INFER_STEPS") or "0").strip()
            try:
                _cap = int(_raw)
            except ValueError:
                _cap = 0
            if _cap > 0 and infer_steps > _cap:
                logger.warning(
                    "[service_generate] dmd_gan/turbo: infer_steps {} exceeds ACESTEP_TURBO_MAX_INFER_STEPS={}, clamping",
                    infer_steps,
                    _cap,
                )
                infer_steps = _cap
            elif _cap <= 0 and infer_steps > 8:
                logger.info(
                    "[service_generate] turbo infer_steps={} (no clamp; set ACESTEP_TURBO_MAX_INFER_STEPS to limit)",
                    infer_steps,
                )'''

# Alternate single-line / f-string form seen in older handlers
OLD_ALT = re.compile(
    r"if self\.config\.is_turbo:\s*\n"
    r"\s*# Limit inference steps to maximum 8\s*\n"
    r"\s*if infer_steps > 8:\s*\n"
    r"\s*logger\.warning\(f?\"\[service_generate\] dmd_gan version: infer_steps .*?clamping to 8\"\)\s*\n"
    r"\s*infer_steps = 8",
    re.S,
)


def main() -> None:
    paths = list(Path("/app").rglob("service_generate_request.py"))
    paths += list(Path("/app").rglob("handler.py"))
    if not paths:
        paths = list(Path(".").rglob("service_generate_request.py"))
    if not paths:
        print("service_generate_request.py not found", file=sys.stderr)
        sys.exit(1)

    n = 0
    for path in paths:
        text = path.read_text()
        if "[XPU-TURBO-STEPS]" in text:
            print(f"Already patched: {path}")
            continue
        if OLD_BLOCK in text:
            text = text.replace(OLD_BLOCK, NEW_BLOCK, 1)
            path.write_text(text)
            print(f"Patched block in {path}")
            n += 1
            continue
        m = OLD_ALT.search(text)
        if m:
            text = OLD_ALT.sub(NEW_BLOCK, text, count=1)
            path.write_text(text)
            print(f"Patched alt form in {path}")
            n += 1
            continue
        # Last resort: neutralize clamp assignment only in that file if warning string present
        if "clamping to 8" in text and "is_turbo" in text:
            text2 = text.replace("infer_steps = 8", "infer_steps = infer_steps  # [XPU-TURBO-STEPS] no clamp")
            if text2 != text:
                path.write_text(text2)
                print(f"Neutralized clamp assignment in {path}")
                n += 1

    if n == 0:
        print("WARNING: no turbo clamp sites patched", file=sys.stderr)
    else:
        print(f"turbo-steps-unclamp: {n} file(s)")


if __name__ == "__main__":
    main()
