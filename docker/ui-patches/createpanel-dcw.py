#!/usr/bin/env python3
"""Add Enable DCW to CreatePanel Expert checkbox grid (after Use ADG).

Upstream ace-step-ui has no DCW UI; buildGradioArgs hard-coded dcw_enabled=true.
Place the control next to Use ADG / Allow LM Batch (after Complete Track Classes).
Default OFF for XPU.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-DCW]"

# Exact upstream block from fspecii/ace-step-ui components/CreatePanel.tsx
ADG_LABEL = '''              <label
                className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400"
                title="Adaptive Dual Guidance: dynamically adjusts CFG for quality. Base model only; slower."
              >
                <input type="checkbox" checked={useAdg} onChange={() => setUseAdg(!useAdg)} />
                {t('useAdg')}
              </label>'''

DCW_LABEL = '''              <label
                className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400"
                title="Differential Correction in Wavelet domain. Experimental; default off on Intel XPU."
              >
                {/* [XPU-DCW] */}
                <input type="checkbox" checked={dcwEnabled} onChange={() => setDcwEnabled(!dcwEnabled)} />
                Enable DCW
              </label>'''


def find_create_panel() -> Path:
    for c in [Path("components/CreatePanel.tsx"), Path("src/components/CreatePanel.tsx")]:
        if c.is_file():
            return c
    hits = list(Path(".").rglob("CreatePanel.tsx"))
    if not hits:
        raise SystemExit("CreatePanel.tsx not found")
    return hits[0]


def patch_create_panel(path: Path) -> None:
    text = path.read_text()

    # 1) useState after useAdg
    if "const [dcwEnabled, setDcwEnabled]" not in text:
        old = "const [useAdg, setUseAdg] = useState(false);"
        if old in text:
            text = text.replace(
                old,
                old + f"\n  const [dcwEnabled, setDcwEnabled] = useState(false); // {MARKER}",
                1,
            )
            print("OK useState dcwEnabled")
        else:
            print("WARN: useAdg useState not found", file=sys.stderr)

    # 2) onGenerate payload: after useAdg,
    if re.search(r"\bdcwEnabled,?\s*$", text, re.M) is None and "dcwEnabled," not in text:
        # handleGenerate object
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

    # 3) Checkbox in Expert grid after Use ADG
    if "Enable DCW" not in text:
        if ADG_LABEL in text:
            text = text.replace(ADG_LABEL, ADG_LABEL + "\n" + DCW_LABEL, 1)
            print("OK checkbox after Use ADG (exact)")
        else:
            # Looser: after useAdg checkbox line
            m = re.search(
                r"(<input type=\"checkbox\" checked=\{useAdg\}[^/]*/>\s*\n\s*\{t\('useAdg'\)\}\s*\n\s*</label>)",
                text,
            )
            if m:
                text = text[: m.end()] + "\n" + DCW_LABEL + text[m.end() :]
                print("OK checkbox after Use ADG (regex)")
            else:
                # After completeTrackClasses section closing, before grid of flags
                needle = "{t('useAdg')}\n              </label>"
                if needle in text:
                    text = text.replace(needle, needle + "\n" + DCW_LABEL, 1)
                    print("OK checkbox after t('useAdg')")
                else:
                    print("WARN: could not place Enable DCW checkbox", file=sys.stderr)

    path.write_text(text)
    print(f"Wrote {path}")


def patch_types_and_api() -> None:
    # types.ts GenerationParams
    for path in [
        Path("types.ts"),
        Path("src/types.ts"),
        *Path(".").rglob("types.ts"),
    ]:
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

    # App.tsx forward params.useAdg → also dcwEnabled
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

    # server generate route destructure + pass-through
    for path in Path(".").rglob("generate.ts"):
        if "node_modules" in str(path):
            continue
        t = path.read_text()
        changed = False
        if "useAdg," in t and "dcwEnabled," not in t:
            t = t.replace("useAdg,", f"useAdg,\n      dcwEnabled, // {MARKER}", 1)
            changed = True
        if "useAdg," in t and "dcwEnabled," in t:
            # also object pass if present once
            if "useAdg," in t and t.count("dcwEnabled") < 2:
                # second site often in the params object sent downstream
                t2 = t.replace(
                    "useAdg,",
                    f"useAdg,\n      dcwEnabled, // {MARKER}",
                    1,
                )
                # only if first already done - avoid infinite; count
                pass
        if changed:
            path.write_text(t)
            print(f"OK generate.ts: {path}")

    # services/api.ts type
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

    # acestep.ts service type + hardcode
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
        if "true, 'double', 0.02, 0.06, 'haar'" in t:
            t = t.replace(
                "true, 'double', 0.02, 0.06, 'haar'",
                f"params.dcwEnabled ?? false, 'double', 0.02, 0.06, 'haar' /* {MARKER} */",
                1,
            )
            print(f"OK acestep.ts DCW args: {path}")
        path.write_text(t)


def main() -> None:
    patch_create_panel(find_create_panel())
    patch_types_and_api()
    print("createpanel-dcw complete")


if __name__ == "__main__":
    main()
