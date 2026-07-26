#!/usr/bin/env python3
"""XPU-safe CreatePanel defaults: FLAC output, ADG stays off.

Upstream turns useAdg ON when you pick a non-turbo DiT (base/sft).
On Intel Arc that path hits apg_forward → RuntimeError:
  Kernel is incompatible with all devices in devs

Also default audio export to FLAC (lossless) instead of MP3.
"""
from pathlib import Path
import sys

candidates = [
    Path("components/CreatePanel.tsx"),
    Path("src/components/CreatePanel.tsx"),
]
p = next((c for c in candidates if c.is_file()), None)
if p is None:
    for c in Path(".").rglob("CreatePanel.tsx"):
        p = c
        break
if p is None or not p.is_file():
    print("CreatePanel.tsx not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
changed = False

# 1) Default audio format → flac
old_fmt = "const [audioFormat, setAudioFormat] = useState<'mp3' | 'flac'>('mp3');"
new_fmt = "const [audioFormat, setAudioFormat] = useState<'mp3' | 'flac'>('flac'); // XPU default: lossless"
if "useState<'mp3' | 'flac'>('flac')" in text:
    print("audioFormat already flac")
elif old_fmt in text:
    text = text.replace(old_fmt, new_fmt, 1)
    changed = True
    print("OK default audioFormat = flac")
else:
    # looser
    if "useState<'mp3' | 'flac'>('mp3')" in text:
        text = text.replace(
            "useState<'mp3' | 'flac'>('mp3')",
            "useState<'mp3' | 'flac'>('flac')",
            1,
        )
        changed = True
        print("OK default audioFormat = flac (loose)")
    else:
        print("WARN: audioFormat useState not found", file=sys.stderr)

# 2) Ensure useAdg default stays false (upstream already false; document)
if "const [useAdg, setUseAdg] = useState(false);" in text:
    print("useAdg default already false")
elif "const [useAdg, setUseAdg] = useState(true);" in text:
    text = text.replace(
        "const [useAdg, setUseAdg] = useState(true);",
        "const [useAdg, setUseAdg] = useState(false); // XPU: APG/ADG breaks on Arc",
        1,
    )
    changed = True
    print("OK useAdg default forced false")

# 3) Critical: selecting base must NOT auto-enable ADG
old_switch = """                          if (!isTurboModel(model.id)) {
                            setInferenceSteps(20);
                            setUseAdg(true);
                          }"""
new_switch = """                          if (!isTurboModel(model.id)) {
                            setInferenceSteps(20);
                            // XPU: do NOT auto-enable ADG — apg_forward fails on Arc
                            // (RuntimeError: Kernel is incompatible with all devices)
                            setUseAdg(false);
                          }"""

if "do NOT auto-enable ADG" in text:
    print("base model ADG auto-on already disabled")
elif old_switch in text:
    text = text.replace(old_switch, new_switch, 1)
    changed = True
    print("OK base/sft no longer auto-enables ADG")
elif "setUseAdg(true)" in text:
    text = text.replace("setUseAdg(true)", "setUseAdg(false) /* XPU: ADG off */", 1)
    changed = True
    print("OK replaced setUseAdg(true) with false")
else:
    print("WARN: setUseAdg(true) on model switch not found (may already be patched)", file=sys.stderr)

if not changed and "do NOT auto-enable ADG" not in text and "useState<'mp3' | 'flac'>('flac')" not in text:
    print("No changes applied", file=sys.stderr)
    sys.exit(1)

p.write_text(text)
print(f"Wrote {p}")
