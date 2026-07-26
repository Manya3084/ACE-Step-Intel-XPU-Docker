#!/usr/bin/env python3
"""Add Enable DCW checkbox to CreatePanel; wire params; default off on XPU.

Root cause of always-on DCW: buildGradioArgs hard-coded
  true, 'double', 0.02, 0.06, 'haar'
Dockerfile.ui now uses params.dcwEnabled ?? false; this patch exposes the toggle.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-DCW]"

CHECKBOX = '''
                  {/* [XPU-DCW] */}
                  <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={dcwEnabled}
                      onChange={(e) => setDcwEnabled(e.target.checked)}
                    />
                    <span>Enable DCW</span>
                  </label>
'''


def find_create_panel() -> Path:
    for c in [Path("components/CreatePanel.tsx"), Path("src/components/CreatePanel.tsx")]:
        if c.is_file():
            return c
    hits = list(Path(".").rglob("CreatePanel.tsx"))
    if not hits:
        raise SystemExit("CreatePanel.tsx not found")
    return hits[0]


def main() -> None:
    path = find_create_panel()
    text = path.read_text()

    # --- useState ---
    if "const [dcwEnabled, setDcwEnabled]" not in text:
        m = re.search(
            r"const \[useAdg, setUseAdg\] = useState\((?:false|true)\);",
            text,
        )
        if m:
            text = (
                text[: m.end()]
                + f"\n  const [dcwEnabled, setDcwEnabled] = useState(false); // {MARKER}"
                + text[m.end() :]
            )
            print("OK dcwEnabled useState")
        else:
            print("WARN: useAdg useState not found", file=sys.stderr)

    # --- pass dcwEnabled next to useAdg in payloads ---
    if re.search(r"\bdcwEnabled\s*,", text) is None:
        text2, n = re.subn(
            r"(\buseAdg\s*,)",
            r"\1 dcwEnabled, /* " + MARKER + " */",
            text,
            count=5,
        )
        if n:
            text = text2
            print(f"OK dcwEnabled in {n} payload site(s)")

    # --- checkbox UI ---
    if "Enable DCW" not in text:
        inserted = False
        # Prefer right after Use ADG checkbox label
        m = re.search(
            r"setUseAdg\(e\.target\.checked\)[\s\S]{0,400}?</label>",
            text,
        )
        if m:
            text = text[: m.end()] + CHECKBOX + text[m.end() :]
            inserted = True
            print("OK checkbox after Use ADG")
        if not inserted:
            m = re.search(r">Use ADG</span>", text)
            if m:
                # find closing label after this
                end = text.find("</label>", m.end())
                if end > 0:
                    end += len("</label>")
                    text = text[:end] + CHECKBOX + text[end:]
                    inserted = True
                    print("OK checkbox after Use ADG span")
        if not inserted and "Allow LM Batch" in text:
            idx = text.find("Allow LM Batch")
            # walk back to start of this label-ish block
            start = text.rfind("<label", 0, idx)
            if start < 0:
                start = idx
            text = text[:start] + CHECKBOX + text[start:]
            inserted = True
            print("OK checkbox before Allow LM Batch")
        if not inserted:
            print("WARN: checkbox placement failed", file=sys.stderr)

    path.write_text(text)
    print(f"Wrote {path}")

    # GenerationParams type
    for tp in Path(".").rglob("*.ts"):
        if "node_modules" in str(tp):
            continue
        t = tp.read_text()
        if "useAdg?" in t and "dcwEnabled?" not in t and (
            "GenerationParams" in t or "interface" in t
        ):
            t2 = re.sub(
                r"(useAdg\?:\s*boolean;?)",
                r"\1\n  dcwEnabled?: boolean; // " + MARKER,
                t,
                count=1,
            )
            if t2 != t:
                tp.write_text(t2)
                print(f"OK type dcwEnabled in {tp}")

    # acestep.ts hardcode fallback
    for sp in Path(".").rglob("acestep.ts"):
        if "node_modules" in str(sp):
            continue
        t = sp.read_text()
        if "true, 'double', 0.02, 0.06, 'haar'" in t:
            t = t.replace(
                "true, 'double', 0.02, 0.06, 'haar'",
                "params.dcwEnabled ?? false, 'double', 0.02, 0.06, 'haar' /* "
                + MARKER
                + " */",
                1,
            )
            sp.write_text(t)
            print(f"OK acestep.ts DCW from params: {sp}")

    print("createpanel-dcw complete")


if __name__ == "__main__":
    main()
