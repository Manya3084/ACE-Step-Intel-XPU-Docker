#!/usr/bin/env python3
"""XPU-safe APG project(): avoid FP64 normalize on Intel Arc.

Upstream apg_guidance.project() does:
  if device_type == "mps": v0, v1 = v0.cpu(), v1.cpu()
  v0, v1 = v0.double(), v1.double()
  F.normalize(...)

Arc A770 has no native FP64 → RuntimeError:
  Kernel is incompatible with all devices in devs

Base / XL-base always call apg_forward. HF/checkpoint copies of
apg_guidance.py must be patched too — transformers may import from
checkpoints/*/ or acestep/models/{base,xl_*}/ not only models/common/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-APG-FP64]"


def _force_xpu_cpu_fallback(text: str) -> tuple[str, bool]:
    """Any form of mps-only CPU move → include xpu."""
    changed = False

    # Already fully marked
    if MARKER in text and 'device_type in ("mps", "xpu")' in text:
        return text, False

    patterns = [
        (
            re.compile(
                r'if\s+device_type\s*==\s*["\']mps["\']\s*:\s*\n'
                r'(\s*)v0,\s*v1\s*=\s*v0\.cpu\(\),\s*v1\.cpu\(\)',
            ),
            r'if device_type in ("mps", "xpu"):  # [XPU-APG-FP64]\n'
            r'\1v0, v1 = v0.cpu(), v1.cpu()',
        ),
        (
            re.compile(
                r"if\s+device_type\s*==\s*[\"']mps[\"']\s*:\s*"
                r"\n\s*v0\s*,\s*v1\s*=\s*v0\.cpu\(\)\s*,\s*v1\.cpu\(\)"
            ),
            'if device_type in ("mps", "xpu"):  # [XPU-APG-FP64]\n'
            "        v0, v1 = v0.cpu(), v1.cpu()",
        ),
    ]
    for pat, repl in patterns:
        new, n = pat.subn(repl, text, count=1)
        if n:
            text = new
            changed = True
            break

    # Bare replace if still only mps
    if 'device_type == "mps"' in text and "v0.cpu()" in text and '("mps", "xpu")' not in text:
        text2 = text.replace(
            'if device_type == "mps":',
            'if device_type in ("mps", "xpu"):  # [XPU-APG-FP64]',
            1,
        )
        if text2 != text:
            text = text2
            changed = True

    # If file has .double() project but NO device cpu fallback at all, inject one
    if (
        "v0.double()" in text
        and "def project" in text
        and '("mps", "xpu")' not in text
        and "v0.cpu()" not in text
    ):
        # Insert after device_type = ...
        text2, n = re.subn(
            r"(device_type\s*=\s*v0\.device\.type\s*\n)",
            r"\1"
            "    origin_device = v0.device\n"
            "    if device_type in (\"mps\", \"xpu\"):  # [XPU-APG-FP64]\n"
            "        v0, v1 = v0.cpu(), v1.cpu()\n",
            text,
            count=1,
        )
        if n:
            text = text2
            changed = True

    return text, changed


def patch_file(path: Path) -> bool:
    try:
        text = path.read_text()
    except Exception as exc:
        print(f"SKIP unreadable {path}: {exc}", file=sys.stderr)
        return False

    if "def project" not in text and "v0.double()" not in text:
        # Stub / re-export only — not actionable
        print(f"SKIP no project()/double in {path}")
        return False

    if MARKER in text and 'device_type in ("mps", "xpu")' in text:
        print(f"Already patched: {path}")
        return False

    text2, changed = _force_xpu_cpu_fallback(text)
    if not changed:
        print(f"WARN: could not patch {path}", file=sys.stderr)
        return False

    path.write_text(text2)
    print(f"OK patched {path}")
    return True


def main() -> None:
    roots = [Path("/app"), Path(".")]
    seen: set[str] = set()
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("apg_guidance.py"):
            key = str(p.resolve()) if p.exists() else str(p)
            if key in seen:
                continue
            seen.add(key)
            paths.append(p)

    if not paths:
        print("apg_guidance.py not found", file=sys.stderr)
        sys.exit(1)

    n = 0
    for p in paths:
        if patch_file(p):
            n += 1
    print(f"apg-xpu-fp64-fallback: {n}/{len(paths)} file(s) updated")


if __name__ == "__main__":
    main()
