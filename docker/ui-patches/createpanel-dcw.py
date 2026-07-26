#!/usr/bin/env python3
"""Add DCW checkbox to CreatePanel and wire GenerationParams.

ace-step-ui did not expose DCW; buildGradioArgs hard-coded dcw_enabled=true.
On XPU default OFF (Arc quality issues / optional experimental). User can
toggle under the same Expert flag row as Use ADG.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-DCW]"


def find_create_panel() -> Path:
    for c in [
        Path("components/CreatePanel.tsx"),
        Path("src/components/CreatePanel.tsx"),
    ]:
        if c.is_file():
            return c
    for c in Path(".").rglob("CreatePanel.tsx"):
        return c
    raise SystemExit("CreatePanel.tsx not found")


def patch_create_panel(path: Path) -> None:
    text = path.read_text()
    if MARKER in text and "dcwEnabled" in text:
        print(f"CreatePanel already has DCW: {path}")
        return

    # 1) useState next to useAdg
    if "const [dcwEnabled, setDcwEnabled]" not in text:
        m = re.search(
            r"const \[useAdg, setUseAdg\] = useState\((?:false|true)\);[^
]*
",
            text,
        )
        if not m:
            print("WARN: useAdg useState not found", file=sys.stderr)
        else:
            insert = (
                m.group(0)
                + "  const [dcwEnabled, setDcwEnabled] = useState(false); "
                + f"// {MARKER} default off on XPU
"
            )
            text = text[: m.start()] + insert + text[m.end() :]
            print("OK added dcwEnabled useState")

    # 2) Include in generate / API payload objects that already pass useAdg
    if "dcwEnabled," not in text and "useAdg," in text:
        text2, n = re.subn(
            r"(useAdg,)(\s*)",n
            r"\1\2dcwEnabled, // " + MARKER + r"\2",
            text,
            count=3,
        )
        if n:
            text = text2
            print(f"OK injected dcwEnabled into {n} object literal(s)")

    # 3) Checkbox near Use ADG label
    if "setDcwEnabled" not in text or "Enable DCW" not in text:
        # Match a simple Use ADG checkbox block variants
        patterns = [
            (
                re.compile(
                    r"(Use ADG</(?:label|span|div)>[\s\S]{0,200}?)",
                    re.I,
                ),
                None,
            ),
        ]
        # Prefer: after useAdg checkbox input onChange
        adg_cb = re.search(
            r"(checked=\{useAdg\}[^>]*>[\s\S]{0,120}?Use ADG[\s\S]{0,80}?)</",
            text,
            re.I,
        )
        checkbox_jsx = (
            f"""
                  {{/* {MARKER} */}}
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={{dcwEnabled}}
                      onChange={{(e) => setDcwEnabled(e.target.checked)}}
                      className="rounded border-zinc-600"
                    />
                    <span>Enable DCW</span>
                  </label>
"""
        )
        if "Enable DCW" not in text:
            # Insert after first occurrence of Use ADG checkbox group
            m = re.search(
                r"([\s\S]*?Use ADG[\s\S]{0,40}?)(\n\s*</(?:label|div)>)",
                text,
            )
            # Simpler: after useAdg onChange line block
            m2 = re.search(
                r"(setUseAdg\(e\.target\.checked\)[\s\S]{0,300}?</label>)",
                text,
            )
            if m2:
                text = text[: m2.end()] + checkbox_jsx + text[m2.end() :]
                print("OK inserted Enable DCW checkbox after Use ADG")
            else:
                # Fallback: append near completeTrackClasses section end flags
                m3 = re.search(
                    r"(Use ADG[\s\S]{0,80})",
                    text,
                )
                if m3:
                    text = (
                        text[: m3.end()]
                        + " / DCW toggle injected below — "
                        + text[m3.end() :]
                    )
                # Last resort: inject before closing of expert flags area with useAdg in JSX
                if "Enable DCW" not in text and "setUseAdg" in text:
                    text = text.replace(
                        "{useAdg}",
                        "{useAdg}" + " /* dcw sibling below */",
                        1,
                    )
                    # Insert a standalone row before Track Name if present
                    if "Track Name" in text and "Enable DCW" not in text:
                        text = text.replace(
                            "Track Name",
                            (
                                f"""Enable DCW"""  # placeholder avoid
                            ),
                            0,  # no
                        )
                    # Clean approach: insert checkbox JSX before first "Use ADG" text node parent ends
                    text = re.sub(
                        r"(>Use ADG</span>)",
                        r"\1",
                        text,
                        count=1,
                    )
                    if "Enable DCW" not in text:
                        text = text.replace(
                            ">Use ADG<",
                            ">Use ADG<",
                            1,
                        )
                        # After completeTrackClasses chips area — search Allow LM Batch
                        if "Allow LM Batch" in text:
                            text = text.replace(
                                "Allow LM Batch",
                                (
                                    "Enable DCW"
                                ),
                                0,
                            )
                        # inject before Allow LM Batch checkbox
                        m_allow = re.search(
                            r"([\t ]*)((?:<label[\s\S]*?)?Allow LM Batch)",
                            text,
                        )
                        if m_allow and "Enable DCW" not in text:
                            ind = m_allow.group(1)
                            block = (
                                f"{ind}<label className=\"flex items-center gap-2 text-sm cursor-pointer\">\n"
                                f"{ind}  <input type=\"checkbox\" checked={{dcwEnabled}} "
                                f"onChange={{(e) => setDcwEnabled(e.target.checked)}} />\n"
                                f"{ind}  <span>Enable DCW</span>\n"
                                f"{ind}</label>\n"
                                f"{ind}{{/* {MARKER} */}}\n"
                            )
                            text = text[: m_allow.start()] + block + text[m_allow.start() :]
                            print("OK inserted Enable DCW before Allow LM Batch")
                        elif "Enable DCW" not in text:
                            print("WARN: could not place checkbox JSX", file=sys.stderr)

    path.write_text(text)
    print(f"Wrote {path}")


def patch_types() -> None:
    for path in Path(".").rglob("*.ts*"):
        if not path.is_file():
            continue
        if "node_modules" in str(path):
            continue
        text = path.read_text()
        if "useAdg" not in text:
            continue
        if "dcwEnabled" in text and MARKER in text:
            continue
        if "interface GenerationParams" in text or "type GenerationParams" in text:
            if "dcwEnabled" not in text:
                text2 = re.sub(
                    r"(useAdg\?:\s*boolean;?)",
                    r"\1\n  dcwEnabled?: boolean; // " + MARKER,
                    text,
                    count=1,
                )
                if text2 != text:
                    path.write_text(text2)
                    print(f"OK GenerationParams.dcwEnabled in {path}")


def patch_acestep_service() -> None:
    """Ensure server maps dcwEnabled → Gradio arg (if not already in Dockerfile)."""
    for path in Path(".").rglob("acestep.ts"):
        if "node_modules" in str(path):
            continue
        text = path.read_text()
        if "true, 'double', 0.02, 0.06, 'haar'" in text:
            text = text.replace(
                "true, 'double', 0.02, 0.06, 'haar'",
                "params.dcwEnabled ?? false, 'double', 0.02, 0.06, 'haar' /* "
                + MARKER
                + " */",
                1,
            )
            path.write_text(text)
            print(f"OK buildGradioArgs dcw from params in {path}")
        elif "params.dcwEnabled" in text:
            print(f"acestep.ts already uses params.dcwEnabled: {path}")


def main() -> None:
    patch_create_panel(find_create_panel())
    patch_types()
    patch_acestep_service()
    print("createpanel-dcw complete")


if __name__ == "__main__":
    main()
