#!/usr/bin/env python3
"""Add Enable DCW to CreatePanel Expert checkbox grid (after Use ADG).

Default ON for XPU now that dcw-xpu-cpu-fallback runs DWT/IDWT on CPU fp32.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-DCW]"

ADG_LABEL = '''              <label
                className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400"
                title="Adaptive Dual Guidance: dynamically adjusts CFG for quality. Base model only; slower."
              >
                <input type="checkbox" checked={useAdg} onChange={() => setUseAdg(!useAdg)} />
                {t('useAdg')}
              </label>'''

DCW_LABEL = '''              <label
                className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400"
                title="Differential Correction in Wavelet domain. DWT runs on CPU (fp32) on Intel XPU."
              >
                {/* [XPU-DCW] */}
                <input type="checkbox" checked={dcwEnabled} onChange={() => setDcwEnabled(!dcwEnabled)} />
                Enable DCW
              </label>'''


def find_create_panel() -> Path:
    for c in [Path("components/CreatePanel.tsx"), Path("src/components/CreatePanel.tsx")]:
        if c.is_file():
            return c
    hits = list(Path(".").rglob("CreatePanel.tsx")
    )
    if not hits:
        raise SystemExit("CreatePanel.tsx not found")
    return hits[0]


def patch_create_panel(path: Path) -> None:
    text = path.read_text()

    # 1) useState after useAdg — default true
    if "const [dcwEnabled, setDcwEnabled]" not in text:
        old = "const [useAdg, setUseAdg] = useState(false);"
        if old in text:
            text = text.replace(
                old,
                old + f"\n  const [dcwEnabled, setDcwEnabled] = useState(true); // {MARKER} default on (CPU DWT)",
                1,
            )
            print("OK useState dcwEnabled=true")
        else:
            print("WARN: useAdg useState not found", file=sys.stderr)
    else:
        # Upgrade previous default false → true
        if "useState(false); // [XPU-DCW]" in text or (
            "const [dcwEnabled, setDcwEnabled] = useState(false)" in text
        ):
            text = text.replace(
                "const [dcwEnabled, setDcwEnabled] = useState(false)",
                "const [dcwEnabled, setDcwEnabled] = useState(true)",
                1,
            )
            print("OK upgraded dcwEnabled default to true")

    # 2) onGenerate payload
    if "dcwEnabled," not in text:
        if "        useAdg,\n        cfgIntervalStart," in text:
            text = text.replace(
                "        useAdg,\n        cfgIntervalStart,",
                f"        useAdg,\n        dcwEnabled, // {MARKER}\n        cfgIntervalStart,",
                1,
            )
            print("OK onGenerate includes dcwEnabled")
        elif "useAdg," in text:
            text = text.replace("useAdg,", f"useAdg,\n        dcwEnabled, // {MARKER}", 1)
            print("OK onGenerate dcwEnabled (loose)")

    # 3) Checkbox
    if "Enable DCW" not in text:
        if ADG_LABEL in text:
            text = text.replace(ADG_LABEL, ADG_LABEL + "\n" + DCW_LABEL, 1)
            print("OK checkbox after Use ADG (exact)")
        else:
            needle = "{t('useAdg')}\n              </label>"
            if needle in text:
                text = text.replace(needle, needle + "\n" + DCW_LABEL, 1)
                print("OK checkbox after t('useAdg')")
            else:
                print("WARN: could not place Enable DCW checkbox", file=sys.stderr)
    else:
        # Refresh title text if old "default off" remains
        text = text.replace(
            "Experimental; default off on Intel XPU.",
            "DWT runs on CPU (fp32) on Intel XPU.",
        )

    path.write_text(text)
    print(f"Wrote {path}")


def patch_types_and_api() -> None:
    for path in [Path("types.ts"), Path("src/types.ts"), *Path(".").rglob("types.ts")]:
        if not path.is_file() or "node_modules" in str(path):
            continue
        t = path.read_text()
        if "useAdg?: boolean" in t and "dcwEnabled?: boolean" not in t:
            t = t.replace(
                "useAdg?: boolean;",
                f"useAdg?: boolean;\n  dcwEnabled?: boolean; // {MARKER}",
                1,
            )
            path.write_text(t)
            print(f"OK types: {path}")

    for path in [Path("App.tsx"), Path("src/App.tsx"), *Path(".").rglob("App.tsx")]:
        if not path.is_file() or "node_modules" in str(path):
            continue
        t = path.read_text()
        if "useAdg: params.useAdg" in t and "dcwEnabled: params.dcwEnabled" not in t:
            t = t.replace(
                "useAdg: params.useAdg,",
                f"useAdg: params.useAdg,\n        dcwEnabled: params.dcwEnabled, // {MARKER}",
                1,
            )
            path.write_text(t)
            print(f"OK App.tsx: {path}")

    for path in Path(".").rglob("generate.ts"):
        if "node_modules" in str(path):
            continue
        t = path.read_text()
        if "useAdg," in t and "dcwEnabled," not in t:
            t = t.replace("useAdg,", f"useAdg,\n      dcwEnabled, // {MARKER}", 1)
            path.write_text(t)
            print(f"OK generate.ts: {path}")

    for path in Path(".").rglob("api.ts"):
        if "node_modules" in str(path):
            continue
        t = path.read_text()
        if "useAdg?: boolean" in t and "dcwEnabled?: boolean" not in t:
            t = t.replace(
                "useAdg?: boolean;",
                f"useAdg?: boolean;\n  dcwEnabled?: boolean; // {MARKER}",
                1,
            )
            path.write_text(t)
            print(f"OK api.ts type: {path}")

    for path in Path(".").rglob("acestep.ts"):
        if "node_modules" in str(path):
            continue
        t = path.read_text()
        if "useAdg?: boolean" in t and "dcwEnabled?: boolean" not in t:
            t = t.replace(
                "useAdg?: boolean;",
                f"useAdg?: boolean;\n  dcwEnabled?: boolean; // {MARKER}",
                1,
            )
        # Default ON when UI omits field
        for old in (
            "params.dcwEnabled ?? false, 'double', 0.02, 0.06, 'haar'",
            "true, 'double', 0.02, 0.06, 'haar'",
            "false, 'double', 0.02, 0.06, 'haar'",
        ):
            if old in t:
                t = t.replace(
                    old,
                    f"params.dcwEnabled ?? true, 'double', 0.02, 0.06, 'haar' /* {MARKER} default on */",
                    1,
                )
                print(f"OK acestep.ts DCW default true: {path}")
                break
        path.write_text(t)


def main() -> None:
    patch_create_panel(find_create_panel())
    patch_types_and_api()
    print("createpanel-dcw complete (default ON)")


if __name__ == "__main__":
    main()
