#!/usr/bin/env python3
"""Patch components/SongList.tsx — XL model badge labels on song rows.

Upstream getModelDisplayName only maps 2B variants (1.5T, 1.5B, …).
XL songs fall through to generic 'v1.5'. Add 1.5XL / 1.5XLS / 1.5XLB.
"""
from pathlib import Path
import sys

candidates = [
    Path("components/SongList.tsx"),
    Path("src/components/SongList.tsx"),
]
p = next((c for c in candidates if c.is_file()), None)
if p is None:
    for c in Path(".").rglob("SongList.tsx"):
        p = c
        break
if p is None or not p.is_file():
    print("SongList.tsx not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
if "acestep-v15-xl-turbo" in text and "1.5XL" in text:
    print("XL badge mapping already present")
    sys.exit(0)

old = """    const mapping: Record<string, string> = {
        'acestep-v15-base': '1.5B',
        'acestep-v15-sft': '1.5S',
        'acestep-v15-turbo-shift1': '1.5TS1',
        'acestep-v15-turbo-shift3': '1.5TS3',
        'acestep-v15-turbo-continuous': '1.5TC',
        'acestep-v15-turbo': '1.5T',
    };
    return mapping[modelId] || 'v1.5';"""

new = """    // ACE-Step-Intel-XPU-Docker: XL 4B badges (and keep 2B labels)
    const mapping: Record<string, string> = {
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
    // Fallback: any *xl* id → 1.5XL rather than generic v1.5
    if (mapping[modelId]) return mapping[modelId];
    if (/xl/i.test(modelId)) return '1.5XL';
    return 'v1.5';"""

if old not in text:
    print("WARN: getModelDisplayName mapping block not found exact match", file=sys.stderr)
    # Try looser: inject after turbo line
    needle = "'acestep-v15-turbo': '1.5T',"
    if needle in text and "'acestep-v15-xl-turbo'" not in text:
        text = text.replace(
            needle,
            needle
            + "\n        'acestep-v15-xl-turbo': '1.5XL',"
            + "\n        'acestep-v15-xl-sft': '1.5XLS',"
            + "\n        'acestep-v15-xl-base': '1.5XLB',",
            1,
        )
        p.write_text(text)
        print(f"OK patched {p} (fallback insert)")
        sys.exit(0)
    sys.exit(1)

text = text.replace(old, new, 1)
p.write_text(text)
print(f"OK patched {p} — XL song badges: 1.5XL / 1.5XLS / 1.5XLB")
