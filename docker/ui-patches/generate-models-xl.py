#!/usr/bin/env python3
"""Patch server/src/routes/generate.ts — include ACE-Step 1.5 XL (4B) DiT models
in the Create advanced-options model dropdown before weights are downloaded.

Upstream ALL_DIT_MODELS only listed 2B turbo/base/sft (+ shift variants).
XL appears in the list only after the checkpoint dir exists on disk; this
patch makes xl-turbo / xl-sft / xl-base always selectable.
"""
from pathlib import Path
import re
import sys

candidates = [
    Path("server/src/routes/generate.ts"),
    Path("src/routes/generate.ts"),
]
p = next((c for c in candidates if c.is_file()), None)
if p is None:
    for c in Path(".").rglob("generate.ts"):
        if "routes" in str(c):
            p = c
            break
if p is None or not p.is_file():
    print("generate.ts not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
if "acestep-v15-xl-turbo" in text:
    print("XL models already present in ALL_DIT_MODELS")
    sys.exit(0)

old = """    const ALL_DIT_MODELS = [
      'acestep-v15-turbo',             // default, from main model repo
      'acestep-v15-base',              // submodel
      'acestep-v15-sft',               // submodel
      'acestep-v15-turbo-shift1',      // submodel
      'acestep-v15-turbo-shift3',      // submodel
      'acestep-v15-turbo-continuous',   // submodel
    ];"""

new = """    // ACE-Step-Intel-XPU-Docker: include XL 4B DiT variants so they appear
    // in Create advanced options before download (selection triggers ensure_dit).
    const ALL_DIT_MODELS = [
      'acestep-v15-turbo',             // default 2B, from main model repo
      'acestep-v15-base',              // 2B submodel
      'acestep-v15-sft',               // 2B submodel
      'acestep-v15-xl-turbo',          // 4B XL turbo (higher quality)
      'acestep-v15-xl-sft',            // 4B XL sft
      'acestep-v15-xl-base',           // 4B XL base
      'acestep-v15-turbo-shift1',      // 2B submodel
      'acestep-v15-turbo-shift3',      // 2B submodel
      'acestep-v15-turbo-continuous',  // 2B submodel
    ];"""

if old in text:
    text = text.replace(old, new, 1)
    p.write_text(text)
    print(f"OK patched {p} — XL models added to ALL_DIT_MODELS")
    sys.exit(0)

# Fallback: insert XL names after the first turbo entry if exact block drifted
pat = re.compile(
    r"(const ALL_DIT_MODELS\s*=\s*\[\s*'acestep-v15-turbo'[^\]]*)(\])",
    re.S,
)
m = pat.search(text)
if not m:
    print("WARN: could not locate ALL_DIT_MODELS block", file=sys.stderr)
    sys.exit(1)

block = m.group(1)
if "xl-turbo" in block:
    print("XL already in list (loose match)")
    sys.exit(0)

insert = """
      'acestep-v15-xl-turbo',          // 4B XL turbo
      'acestep-v15-xl-sft',            // 4B XL sft
      'acestep-v15-xl-base',           // 4B XL base,"""
# place after the continuous / last known 2B entry if present, else after turbo
if "'acestep-v15-turbo-continuous'" in block:
    block2 = block.replace(
        "'acestep-v15-turbo-continuous',",
        "'acestep-v15-turbo-continuous'," + insert,
        1,
    )
else:
    block2 = block.replace(
        "'acestep-v15-turbo',",
        "'acestep-v15-turbo'," + insert,
        1,
    )

text = text[: m.start(1)] + block2 + text[m.end(1) :]
p.write_text(text)
print(f"OK patched {p} (fallback) — XL models added")
