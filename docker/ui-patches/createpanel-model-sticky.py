#!/usr/bin/env python3
"""Patch components/CreatePanel.tsx — sticky DiT selection + XL labels.

Upstream refreshModels() always overwrites selectedModel with the backend
active model after every generation. If /v1/models still reports turbo
(or races), the dropdown snaps to 1.5T even when the user chose XL.

Policy: keep the user's localStorage choice when it is still in the list.
Only fall back to backend is_active on first load with no stored model.
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

old_refresh = """          setFetchedModels(models);
          // Always sync to the backend's active model
          const active = models.find((m: any) => m.is_active);
          if (active) {
            setSelectedModel(active.name);
            localStorage.setItem('ace-model', active.name);
          }"""

new_refresh = """          setFetchedModels(models);
          // ACE-Step-Intel-XPU-Docker: do NOT force-reset the dropdown to
          // backend active after every gen — that snapped XL back to turbo.
          // Prefer the user's explicit localStorage / current selection.
          const stored = localStorage.getItem('ace-model');
          const active = models.find((m: any) => m.is_active);
          if (stored && models.some((m: any) => m.name === stored)) {
            setSelectedModel(stored);
          } else if (active) {
            setSelectedModel(active.name);
            localStorage.setItem('ace-model', active.name);
          }"""

if "do NOT force-reset the dropdown" in text:
    print("sticky model selection already present")
elif old_refresh in text:
    text = text.replace(old_refresh, new_refresh, 1)
    changed = True
    print("OK sticky selectedModel on refreshModels")
else:
    print("WARN: refreshModels active-sync block not found exact", file=sys.stderr)
    # looser fallback
    needle = "// Always sync to the backend's active model"
    if needle in text:
        text = text.replace(
            needle,
            "// Prefer user selection (ACE-Step-Intel-XPU-Docker sticky model)",
            1,
        )
        text = text.replace(
            """          const active = models.find((m: any) => m.is_active);
          if (active) {
            setSelectedModel(active.name);
            localStorage.setItem('ace-model', active.name);
          }""",
            """          const stored = localStorage.getItem('ace-model');
          const active = models.find((m: any) => m.is_active);
          if (stored && models.some((m: any) => m.name === stored)) {
            setSelectedModel(stored);
          } else if (active) {
            setSelectedModel(active.name);
            localStorage.setItem('ace-model', active.name);
          }""",
            1,
        )
        changed = True
        print("OK sticky selectedModel (fallback)")
    else:
        print("FAIL: could not patch refreshModels", file=sys.stderr)
        sys.exit(1)

# XL display names in Create panel header dropdown
old_map = """    const mapping: Record<string, string> = {
      'acestep-v15-base': '1.5B',
      'acestep-v15-sft': '1.5S',
      'acestep-v15-turbo-shift1': '1.5TS1',
      'acestep-v15-turbo-shift3': '1.5TS3',
      'acestep-v15-turbo-continuous': '1.5TC',
      'acestep-v15-turbo': '1.5T',
    };
    return mapping[modelId] || modelId;"""

new_map = """    const mapping: Record<string, string> = {
      'acestep-v15-base': '1.5B',
      'acestep-v15-sft': '1.5S',
      'acestep-v15-turbo-shift1': '1.5TS1',
      'acestep-v15-turbo-shift3': '1.5TS3',
      'acestep-v15-turbo-continuous': '1.5TC',
      'acestep-v15-turbo': '1.5T',
      'acestep-v15-xl-turbo': '1.5XL',
      'acestep-v15-xl-sft': '1.5XLS',
      'acestep-v15-xl-base': '1.5XLB',
    };
    if (mapping[modelId]) return mapping[modelId];
    if (/xl/i.test(modelId)) return '1.5XL';
    return modelId;"""

if "'acestep-v15-xl-turbo': '1.5XL'" in text and "CreatePanel" in str(p):
    print("XL CreatePanel badges already present")
elif old_map in text:
    text = text.replace(old_map, new_map, 1)
    changed = True
    print("OK XL labels in CreatePanel getModelDisplayName")
else:
    needle = "'acestep-v15-turbo': '1.5T',"
    if needle in text and "'acestep-v15-xl-turbo'" not in text:
        text = text.replace(
            needle,
            needle
            + "\n      'acestep-v15-xl-turbo': '1.5XL',"
            + "\n      'acestep-v15-xl-sft': '1.5XLS',"
            + "\n      'acestep-v15-xl-base': '1.5XLB',",
            1,
        )
        changed = True
        print("OK XL labels (fallback insert)")

if not changed and "do NOT force-reset" not in text and "sticky model" not in text:
    sys.exit(1)

p.write_text(text)
print(f"Wrote {p}")
