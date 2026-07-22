#!/usr/bin/env python3
"""Patch acestep/training/trainer.py for Intel XPU (verified on Arc A770).

Lightning Fabric does not accept accelerator='xpu'. On XPU we use the basic
training loop so DiT/LoRA stay on torch.device('xpu').

Also maps accelerator away from 'xpu' if Fabric is still entered.
"""
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

text = TARGET.read_text(encoding="utf-8")
orig = text

# --- LoRATrainer.train_from_preprocessed ---
old1 = """            if LIGHTNING_AVAILABLE:
                yield from self._train_with_fabric(
                    data_module, training_state, resume_from
                )
            else:
                yield from self._train_basic(data_module, training_state)"""

new1 = """            # Intel XPU: Lightning Fabric has no accelerator="xpu".
            # Use basic loop so DiT/LoRA remain on torch.device("xpu").
            if LIGHTNING_AVAILABLE and self.module.device_type != "xpu":
                yield from self._train_with_fabric(
                    data_module, training_state, resume_from
                )
            else:
                if self.module.device_type == "xpu":
                    yield (
                        0,
                        0.0,
                        "ℹ️ XPU: basic training loop (Fabric has no accelerator=xpu)",
                    )
                yield from self._train_basic(data_module, training_state)"""

if old1 in text:
    text = text.replace(old1, new1, 1)
    print("LoRA train_from_preprocessed: XPU basic loop")
else:
    print("WARN: LoRA fabric dispatch block not found", file=sys.stderr)

# --- LoKRTrainer.train_from_preprocessed ---
old2 = """            if LIGHTNING_AVAILABLE:
                yield from self._train_with_fabric(data_module, training_state)
            else:
                yield from self._train_basic(data_module, training_state)"""

new2 = """            if LIGHTNING_AVAILABLE and self.module.device_type != "xpu":
                yield from self._train_with_fabric(data_module, training_state)
            else:
                if self.module.device_type == "xpu":
                    yield (
                        0,
                        0.0,
                        "ℹ️ XPU: basic training loop (Fabric has no accelerator=xpu)",
                    )
                yield from self._train_basic(data_module, training_state)"""

if old2 in text:
    text = text.replace(old2, new2, 1)
    print("LoKR train_from_preprocessed: XPU basic loop")
else:
    print("WARN: LoKR fabric dispatch block not found", file=sys.stderr)

# --- Fabric accelerator string (safety if Fabric still used) ---
old_acc = (
    "        accelerator = (\n"
    '            device_type if device_type in ("cuda", "xpu", "mps", "cpu") else "auto"\n'
    "        )"
)
new_acc = (
    "        # Fabric does not register accelerator=\"xpu\"\n"
    '        if device_type == "xpu":\n'
    '            accelerator = "cpu"\n'
    "        else:\n"
    '            accelerator = (\n'
    '                device_type if device_type in ("cuda", "mps", "cpu") else "auto"\n'
    "            )"
)
if old_acc in text:
    text = text.replace(old_acc, new_acc)
    print("Fabric accelerator: xpu -> cpu (safety)")
else:
    text2, n = re.subn(
        r'device_type if device_type in \("cuda", "xpu", "mps", "cpu"\) else "auto"',
        '("cpu" if device_type == "xpu" else (device_type if device_type in ("cuda", "mps", "cpu") else "auto"))',
        text,
    )
    text = text2
    print(f"Fabric accelerator regex replacements: {n}")

if text == orig:
    print("ERROR: no changes applied", file=sys.stderr)
    sys.exit(1)

if 'device_type != "xpu"' not in text:
    print("ERROR: XPU basic-loop guard missing after patch", file=sys.stderr)
    sys.exit(1)

TARGET.write_text(text, encoding="utf-8")
print(f"OK patched {TARGET}")
