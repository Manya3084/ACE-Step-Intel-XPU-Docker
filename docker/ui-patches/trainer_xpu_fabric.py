#!/usr/bin/env python3
"""Patch acestep/training/trainer.py for Intel XPU.

Lightning Fabric does not accept accelerator='xpu'. On XPU we use the basic
training loop so DiT/LoRA stay on torch.device('xpu').

Also maps accelerator string away from 'xpu' if Fabric is still used.
"""
from pathlib import Path
import re
import sys

TARGET = Path("/app/acestep/training/trainer.py")
if not TARGET.is_file():
    # host / build context
    for c in [
        Path("acestep/training/trainer.py"),
        Path("/app/acestep/training/trainer.py"),
    ]:
        if c.is_file():
            TARGET = c
            break

if not TARGET.is_file():
    print("trainer.py not found", file=sys.stderr)
    sys.exit(1)

text = TARGET.read_text(encoding="utf-8")
orig = text

# Prefer basic loop on XPU (both LoRA and LoKR trainers)
text = text.replace(
    """            if LIGHTNING_AVAILABLE:
                yield from self._train_with_fabric(
                    data_module, training_state, resume_from
                )
            else:
                yield from self._train_basic(data_module, training_state)""",
    """            # Lightning Fabric has no accelerator="xpu" — use basic loop on XPU
            # so the DiT stays on torch.device("xpu").
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
                yield from self._train_basic(data_module, training_state)""",
)

text = text.replace(
    """            if LIGHTNING_AVAILABLE:
                yield from self._train_with_fabric(data_module, training_state)
            else:
                yield from self._train_basic(data_module, training_state)""",
    """            if LIGHTNING_AVAILABLE and self.module.device_type != "xpu":
                yield from self._train_with_fabric(data_module, training_state)
            else:
                if self.module.device_type == "xpu":
                    yield (
                        0,
                        0.0,
                        "ℹ️ XPU: basic training loop (Fabric has no accelerator=xpu)",
                    )
                yield from self._train_basic(data_module, training_state)""",
)

# If Fabric path is still entered, never pass accelerator="xpu"
old_acc = '''        accelerator = (
            device_type if device_type in ("cuda", "xpu", "mps", "cpu") else "auto"
        )'''
new_acc = '''        # Fabric does not register "xpu" — map to cpu name only if forced here.
        # Prefer routing XPU to _train_basic above instead.
        if device_type == "xpu":
            accelerator = "cpu"
        else:
            accelerator = (
                device_type if device_type in ("cuda", "mps", "cpu") else "auto"
            )'''

if old_acc in text:
    text = text.replace(old_acc, new_acc)
    print("mapped Fabric accelerator xpu -> cpu")
else:
    # looser replace
    text2, n = re.subn(
        r'accelerator\s*=\s*\(\s*device_type\s+if\s+device_type\s+in\s*\([^)]*xpu[^)]*\)\s+else\s+["\']auto["\']\s*\)',
        'accelerator = ("cpu" if device_type == "xpu" else (device_type if device_type in ("cuda", "mps", "cpu") else "auto"))',
        text,
        flags=re.S,
    )
    text = text2
    print(f"regex accelerator map count={n}")

if text == orig:
    print("WARNING: no changes applied", file=sys.stderr)
    sys.exit(1)

TARGET.write_text(text, encoding="utf-8")
print(f"OK patched {TARGET}")
