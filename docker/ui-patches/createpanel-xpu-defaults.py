#!/usr/bin/env python3
"""XPU-safe CreatePanel defaults: FLAC output, ADG off, DiT guidance profile.

Upstream turns useAdg ON when you pick a non-turbo DiT (base/sft).
On Intel Arc that path hits apg_forward → RuntimeError:
  Kernel is incompatible with all devices in devs

Also default audio export to FLAC (lossless) instead of MP3.

DiT guidance profile (matches Gradio model_config + live switch):
  turbo / xl-turbo → steps 8
  base / sft / xl-base / xl-sft → steps 50
  ADG always false on XPU
"""
from pathlib import Path
import re
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

# 2) Ensure useAdg default stays false
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

# 3) Full DiT guidance profile on model select (replaces upstream / older XPU partial)
old_profiles = [
    # upstream
    """                          if (!isTurboModel(model.id)) {
                            setInferenceSteps(20);
                            setUseAdg(true);
                          }""",
    # older xpu partial that only forced ADG false with steps 20
    """                          if (!isTurboModel(model.id)) {
                            setInferenceSteps(20);
                            // XPU: do NOT auto-enable ADG — apg_forward fails on Arc
                            // (RuntimeError: Kernel is incompatible with all devices)
                            setUseAdg(false);
                          }""",
    # selectDitModel body from createpanel-dit-live-switch
    """    if (!isTurboModel(modelId)) {
      setInferenceSteps(20);
      setUseAdg(true);
    }""",
    """    if (!isTurboModel(modelId)) {
      setInferenceSteps(20);
      setUseAdg(false);
    }""",
]

new_profile_menu = """                          // [XPU-DIT-PROFILE] match Gradio model_config for this DiT
                          {
                            const id = model.id.toLowerCase();
                            const turbo = id.includes('turbo');
                            const sft = id.includes('sft') && !turbo;
                            const base = id.includes('base') && !turbo && !sft;
                            setUseAdg(false); // XPU: ADG unsafe on Arc
                            if (turbo) setInferenceSteps(8);
                            else if (sft || base) setInferenceSteps(50);
                            else setInferenceSteps(32);
                          }"""

new_profile_select = """    // [XPU-DIT-PROFILE] match Gradio model_config for this DiT
    {
      const id = modelId.toLowerCase();
      const turbo = id.includes('turbo');
      const sft = id.includes('sft') && !turbo;
      const base = id.includes('base') && !turbo && !sft;
      setUseAdg(false); // XPU: ADG unsafe on Arc
      if (turbo) setInferenceSteps(8);
      else if (sft || base) setInferenceSteps(50);
      else setInferenceSteps(32);
    }"""

if "[XPU-DIT-PROFILE]" in text and "setInferenceSteps(50)" in text:
    print("DiT guidance profile already present")
else:
    for old in old_profiles:
        if old in text:
            repl = new_profile_select if "modelId" in old else new_profile_menu
            text = text.replace(old, repl, 1)
            changed = True
            print("OK applied DiT guidance profile")
            break
    else:
        if "setUseAdg(true)" in text:
            text = text.replace("setUseAdg(true)", "setUseAdg(false) /* XPU: ADG off */", 1)
            changed = True
            print("OK replaced setUseAdg(true) with false")
        else:
            print("WARN: model-switch profile site not found", file=sys.stderr)

if not changed and "[XPU-DIT-PROFILE]" not in text and "useState<'mp3' | 'flac'>('flac')" not in text:
    print("No changes applied", file=sys.stderr)
    sys.exit(1)

p.write_text(text)
print(f"Wrote {p}")
