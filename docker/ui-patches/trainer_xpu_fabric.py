#!/usr/bin/env python3
"""Patch acestep/training/trainer.py for Intel XPU (Arc A770 verified).

Lightning Fabric does not accept accelerator='xpu'. On XPU we skip Fabric and
use the basic training loop so DiT/LoRA stay on torch.device('xpu').

Uses line-based matching so upstream whitespace / signature drift does not
silently skip the patch (previous exact-string blocks regressed on rebuild).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

candidates = [
    Path("/app/acestep/training/trainer.py"),
    Path("acestep/training/trainer.py"),
]
TARGET = next((p for p in candidates if p.is_file()), None)
if TARGET is None:
    print("trainer.py not found", file=sys.stderr)
    sys.exit(1)

lines = TARGET.read_text(encoding="utf-8").splitlines(True)
orig = "".join(lines)
changed = 0

# 1) Gate every `if LIGHTNING_AVAILABLE:` that dispatches to _train_with_fabric
for i, line in enumerate(lines):
    if line.strip() != "if LIGHTNING_AVAILABLE:":
        continue
    window = "".join(lines[i + 1 : i + 6])
    if "_train_with_fabric" not in window:
        continue
    indent = line[: len(line) - len(line.lstrip())]
    lines[i] = (
        f'{indent}if LIGHTNING_AVAILABLE and self.module.device_type != "xpu":\n'
    )
    changed += 1
    print(f"gated Fabric at line {i + 1}")

text = "".join(lines)

# 2) Never pass accelerator="xpu" into Fabric kwargs
text2, n_acc = re.subn(
    r'device_type if device_type in \("cuda", "xpu", "mps", "cpu"\) else "auto"',
    '("cpu" if device_type == "xpu" else '
    '(device_type if device_type in ("cuda", "mps", "cpu") else "auto"))',
    text,
)
text = text2
if n_acc:
    print(f"accelerator xpu->cpu safety replacements: {n_acc}")
    changed += n_acc

# 3) Explicit accelerator="xpu" assignments
text2, n_lit = re.subn(
    r'accelerator\s*=\s*["\']xpu["\']',
    'accelerator="cpu"',
    text,
    flags=re.I,
)
text = text2
if n_lit:
    print(f"literal accelerator=xpu rewrites: {n_lit}")
    changed += n_lit

if changed < 1 or 'device_type != "xpu"' not in text:
    print("ERROR: XPU Fabric bypass not applied", file=sys.stderr)
    sys.exit(1)

if text == orig:
    print("ERROR: no file changes", file=sys.stderr)
    sys.exit(1)

TARGET.write_text(text, encoding="utf-8")
print(f"OK patched {TARGET} ({changed} edits)")
