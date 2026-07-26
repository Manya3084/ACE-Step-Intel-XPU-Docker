#!/usr/bin/env python3
"""Persist last DiT/LM to /app/checkpoints/.last_* after every successful switch.

CRITICAL: never embed a real newline inside a Python string in the injected
helper (that caused SyntaxError: unterminated string in api_routes.py).
Use chr(10) for the trailing newline in the file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-LAST-MODEL]"

# Use chr(10) — do NOT put \\n or real newlines inside quoted string literals
# that will be written into api_routes.py.
HELPER = '''
def _xpu_persist_last_model(dit_name: str = "", lm_name: str = "") -> None:
    """[XPU-LAST-MODEL] Save last DiT/LM into /app/checkpoints (host volume)."""
    try:
        from pathlib import Path as _P
        base = _P("/app/checkpoints")
        base.mkdir(parents=True, exist_ok=True)
        if dit_name and str(dit_name).strip():
            name = str(dit_name).strip()
            aliases = {
                "1.5xl soft": "acestep-v15-xl-sft",
                "1.5xl-soft": "acestep-v15-xl-sft",
                "xl-soft": "acestep-v15-xl-sft",
                "soft": "acestep-v15-xl-sft",
                "1.5xl base": "acestep-v15-xl-base",
                "1.5xlb": "acestep-v15-xl-base",
            }
            key = name.lower()
            name = aliases.get(key, name)
            (base / ".last_dit_model").write_text(name + chr(10))
            print("[XPU-LAST-MODEL] wrote .last_dit_model=" + name)
        if lm_name and str(lm_name).strip():
            name = str(lm_name).strip()
            (base / ".last_lm_model").write_text(name + chr(10))
            print("[XPU-LAST-MODEL] wrote .last_lm_model=" + name)
    except Exception as _e:
        print("[XPU-LAST-MODEL] persist failed: " + str(_e))
'''


def _repair_broken_helper(text: str) -> str:
    """Remove any previous broken _xpu_persist_last_model (unterminated strings)."""
    # Nuke from def _xpu_persist_last_model through the next top-level def/class
    # or until we have a balanced function — prefer regex from def to print persist failed
    patterns = [
        # Broken form with unterminated quote
        re.compile(
            r"\ndef _xpu_persist_last_model\([\s\S]*?(?=\n(?:def |class |async def ))",
            re.M,
        ),
        re.compile(
            r"def _xpu_persist_last_model\([\s\S]*?persist failed[\s\S]*?\n",
            re.M,
        ),
    ]
    for pat in patterns:
        if pat.search(text):
            text = pat.sub("\n", text, count=1)
            print("Removed old/broken _xpu_persist_last_model block")
            break
    # Also fix any standalone broken write_text lines left over
    text = re.sub(
        r'\(base / "\.last_dit_model"\)\.write_text\(name \+\s*\n\s*""\)',
        '(base / ".last_dit_model").write_text(name + chr(10))',
        text,
    )
    text = re.sub(
        r'\(base / "\.last_lm_model"\)\.write_text\(name \+\s*\n\s*""\)',
        '(base / ".last_lm_model").write_text(name + chr(10))',
        text,
    )
    return text


def patch_api_routes(path: Path) -> bool:
    text = path.read_text()
    text = _repair_broken_helper(text)
    changed = True  # always re-apply clean helper after repair attempt

    if "_xpu_persist_last_model" in text and "chr(10)" in text and "[XPU-LAST-MODEL]" in text:
        # helper already good
        if "write_text(name +" in text and "chr(10)" not in text.split("_xpu_persist_last_model")[1][:800]:
            pass  # still need refresh
        else:
            # Ensure call sites exist; helper ok
            changed = False

    if "def _xpu_persist_last_model" not in text or "chr(10)" not in text:
        if "from loguru import logger" in text:
            text = text.replace(
                "from loguru import logger",
                "from loguru import logger\n" + HELPER,
                1,
            )
        else:
            text = HELPER + "\n" + text
        changed = True
        print(f"OK inserted clean helper in {path}")
    elif "chr(10)" not in text:
        # replace body only
        text = re.sub(
            r"def _xpu_persist_last_model\([\s\S]*?print\(\[XPU-LAST-MODEL\] persist failed[\s\S]*?\)\n",
            HELPER.strip() + "\n",
            text,
            count=1,
        )
        changed = True
        print("OK replaced helper with chr(10) version")

    # DiT persist call sites
    if "_xpu_persist_last_model(dit_name=" not in text:
        if "DiT loaded" in text:
            lines = text.splitlines(keepends=True)
            out = []
            done = False
            for line in lines:
                out.append(line)
                if not done and "DiT loaded" in line and "logger" in line:
                    indent = re.match(r"^(\s*)", line).group(1)
                    out.append(
                        f"{indent}_xpu_persist_last_model(dit_name=str(loaded))  # {MARKER}\n"
                    )
                    done = True
                    changed = True
                    print("OK DiT persist after DiT loaded")
            text = "".join(out)
        if "_xpu_persist_last_model(dit_name=" not in text and '"loaded_model"' in text:
            text = text.replace(
                '"loaded_model": loaded',
                '_xpu_persist_last_model(dit_name=str(loaded))  # '
                + MARKER
                + '\n        "loaded_model": loaded',
                1,
            )
            changed = True
            print("OK DiT persist near loaded_model")

    if "_xpu_persist_last_model(lm_name=" not in text:
        if "LM loaded" in text:
            lines = text.splitlines(keepends=True)
            out = []
            done = False
            for line in lines:
                out.append(line)
                if not done and "LM loaded" in line and "logger" in line:
                    indent = re.match(r"^(\s*)", line).group(1)
                    out.append(
                        f"{indent}_xpu_persist_last_model(lm_name=str(loaded))  # {MARKER}\n"
                    )
                    done = True
                    changed = True
                    print("OK LM persist after LM loaded")
            text = "".join(out)
        if "_xpu_persist_last_model(lm_name=" not in text and '"loaded_lm_model"' in text:
            text = text.replace(
                '"loaded_lm_model": loaded',
                '_xpu_persist_last_model(lm_name=str(loaded))  # '
                + MARKER
                + '\n        "loaded_lm_model": loaded',
                1,
            )
            changed = True
            print("OK LM persist near loaded_lm_model")

    # Validate syntax before writing
    try:
        compile(text, str(path), "exec")
    except SyntaxError as e:
        print(f"ERROR: patched api_routes still invalid: {e}", file=sys.stderr)
        # last resort: strip helper and call sites entirely so Gradio can start
        text2 = path.read_text() if path.is_file() else text
        text2 = re.sub(
            r"\ndef _xpu_persist_last_model\([\s\S]*?(?=\n(?:def |class |async def ))",
            "\n",
            text2,
            count=1,
        )
        text2 = text2.replace(
            f"_xpu_persist_last_model(dit_name=str(loaded))  # {MARKER}\n", ""
        )
        text2 = text2.replace(
            f"_xpu_persist_last_model(lm_name=str(loaded))  # {MARKER}\n", ""
        )
        try:
            compile(text2, str(path), "exec")
            path.write_text(text2)
            print("RECOVERY: removed broken persist helper so API can import")
            return True
        except SyntaxError as e2:
            print(f"RECOVERY failed: {e2}", file=sys.stderr)
            sys.exit(1)

    path.write_text(text)
    print(f"Wrote {path}")
    return True


def main() -> None:
    paths = []
    for root in (Path("/app"), Path(".")):
        if root.is_dir():
            paths.extend(root.rglob("api_routes.py"))
    seen = set()
    files = []
    for p in paths:
        k = str(p.resolve()) if p.exists() else str(p)
        if "node_modules" in k:
            continue
        if k not in seen:
            seen.add(k)
            files.append(p)
    if not files:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)
    n = sum(1 for p in files if patch_api_routes(p))
    print(f"persist-last-model: {n} file(s) updated")


if __name__ == "__main__":
    main()
