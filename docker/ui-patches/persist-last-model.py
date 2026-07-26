#!/usr/bin/env python3
"""Write /app/checkpoints/.last_dit_model and .last_lm_model after live switch.

Entrypoint restores these so boot matches the last UI selection instead of
always acestep-v15-turbo + 1.7B.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-LAST-MODEL]"

HELPER = '''
def _xpu_persist_last_model(dit_name: str = "", lm_name: str = "") -> None:
    """[XPU-LAST-MODEL] Save last DiT/LM into /app/checkpoints (host volume)."""
    try:
        from pathlib import Path as _P
        base = _P("/app/checkpoints")
        base.mkdir(parents=True, exist_ok=True)
        if dit_name and str(dit_name).strip():
            name = str(dit_name).strip()
            (base / ".last_dit_model").write_text(name + "\\n")
            print(f"[XPU-LAST-MODEL] wrote .last_dit_model={name}")
        if lm_name and str(lm_name).strip():
            name = str(lm_name).strip()
            (base / ".last_lm_model").write_text(name + "\\n")
            print(f"[XPU-LAST-MODEL] wrote .last_lm_model={name}")
    except Exception as _e:
        print(f"[XPU-LAST-MODEL] persist failed: {_e}")
'''


def patch_api_routes(path: Path) -> bool:
    text = path.read_text()
    changed = False

    if "_xpu_persist_last_model" not in text:
        if "from loguru import logger" in text:
            text = text.replace(
                "from loguru import logger",
                "from loguru import logger\n" + HELPER,
                1,
            )
        else:
            text = HELPER + "\n" + text
        changed = True
        print(f"OK helper in {path}")

    # After successful LM load log
    if "_xpu_persist_last_model(lm_name" not in text:
        # live-lm-reinit success: logger.info(f"[v1/init] LM loaded: {loaded}")
        patterns = [
            (
                r'(logger\.info\(f?"\[v1/init\] LM loaded: \{loaded\}"\))',
                r'\1\n    _xpu_persist_last_model(lm_name=str(loaded))  # '
                + MARKER,
            ),
            (
                r'(logger\.info\([^\n]*LM loaded:[^\n]*\))',
                r'\1\n    _xpu_persist_last_model(lm_name=str(loaded) if "loaded" in dir() else lm_model_path)  # '
                + MARKER,
            ),
        ]
        for pat, repl in patterns:
            text2, n = re.subn(pat, repl, text, count=1)
            if n:
                text = text2
                changed = True
                print("OK LM persist after LM loaded")
                break
        if "_xpu_persist_last_model(lm_name" not in text:
            # Insert before return of _switch_lm_model_sync
            if "def _switch_lm_model_sync" in text and '"loaded_lm_model": loaded' in text:
                text = text.replace(
                    '"loaded_lm_model": loaded',
                    '_xpu_persist_last_model(lm_name=str(loaded))  # '
                    + MARKER
                    + '\n        "loaded_lm_model": loaded',
                    1,
                )
                changed = True
                print("OK LM persist near loaded_lm_model return")

    # After successful DiT load
    if "_xpu_persist_last_model(dit_name" not in text:
        if "DiT loaded:" in text:
            lines = text.splitlines(keepends=True)
            out = []
            done = False
            for line in lines:
                out.append(line)
                if (
                    not done
                    and "DiT loaded" in line
                    and "logger" in line
                    and "_xpu_persist_last_model" not in line
                ):
                    indent = re.match(r"^(\s*)", line).group(1)
                    out.append(
                        f"{indent}_xpu_persist_last_model(dit_name=str(loaded))  # {MARKER}\n"
                    )
                    done = True
                    changed = True
                    print("OK DiT persist after DiT loaded line")
            text = "".join(out)
        if "_xpu_persist_last_model(dit_name" not in text and '"loaded_model":' in text:
            text2, n = re.subn(
                r'("loaded_model":\s*loaded)',
                r'_xpu_persist_last_model(dit_name=str(loaded))  # '
                + MARKER
                + r'\n        \1',
                text,
                count=1,
            )
            if n:
                text = text2
                changed = True
                print("OK DiT persist near loaded_model")

    if changed:
        path.write_text(text)
        print(f"Wrote {path}")
        return True
    print(f"No change: {path}")
    return False


def main() -> None:
    paths = []
    for root in (Path("/app"), Path(".")):
        if root.is_dir():
            paths.extend(root.rglob("api_routes.py"))
    seen = set()
    files = []
    for p in paths:
        k = str(p.resolve()) if p.exists() else str(p)
        if k not in seen and "node_modules" not in k and "gradio" in k:
            seen.add(k)
            files.append(p)
    if not files:
        # any api_routes
        for p in paths:
            k = str(p.resolve()) if p.exists() else str(p)
            if k not in seen and "node_modules" not in k:
                seen.add(k)
                files.append(p)
    if not files:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)
    n = sum(1 for p in files if patch_api_routes(p))
    print(f"persist-last-model: {n} file(s) updated")


if __name__ == "__main__":
    main()
