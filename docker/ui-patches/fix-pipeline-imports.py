#!/usr/bin/env python3
"""Restore critical imports in acestep_v15_pipeline.py if a prior patch removed them.

Symptom:
  NameError: name 'get_gpu_config' is not defined

Cause:
  format-ram-headroom (old) deleted the import block between a prepended
  helper and the next top-level def.
"""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = [
    ("get_gpu_config", "from acestep.gpu_config import get_gpu_config"),
    ("get_gpu_config", "from acestep.gpu_config import get_gpu_config, get_gpu_memory_gb"),
]


def _ensure_get_gpu_config(text: str) -> str:
    if "get_gpu_config" in text and (
        "from acestep.gpu_config import" in text
        or "import acestep.gpu_config" in text
    ):
        # If the name is used and some import exists, still verify the symbol
        if "from acestep.gpu_config import get_gpu_config" in text:
            return text
        if "import acestep.gpu_config as" in text:
            return text

    # Prefer adding next to other acestep imports
    needle = "from acestep."
    idx = text.find(needle)
    line = "from acestep.gpu_config import get_gpu_config\n"
    if idx >= 0:
        # insert before first acestep import line
        return text[:idx] + line + text[idx:]

    # After __future__ / module docstring
    if text.startswith('"""') or text.startswith("'''"):
        q = text[:3]
        end = text.find(q, 3)
        if end > 0:
            end = end + 3
            if end < len(text) and text[end] == "\n":
                end += 1
            return text[:end] + line + text[end:]

    return line + text


def main() -> None:
    paths = list(Path("/app").rglob("acestep_v15_pipeline.py"))
    if not paths:
        paths = list(Path(".").rglob("acestep_v15_pipeline.py"))
    if not paths:
        print("acestep_v15_pipeline.py not found", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        text = path.read_text()
        if "get_gpu_config()" in text or "get_gpu_config (" in text:
            if "from acestep.gpu_config import get_gpu_config" not in text:
                text = _ensure_get_gpu_config(text)
                path.write_text(text)
                print(f"Restored get_gpu_config import in {path}")
            else:
                print(f"get_gpu_config import OK: {path}")
        else:
            # still ensure import for safety if symbol referenced differently
            if "get_gpu_config" in text and "from acestep.gpu_config import get_gpu_config" not in text:
                text = _ensure_get_gpu_config(text)
                path.write_text(text)
                print(f"Restored get_gpu_config import in {path}")
            else:
                print(f"No get_gpu_config usage or already OK: {path}")

    print("fix-pipeline-imports complete")


if __name__ == "__main__":
    main()
