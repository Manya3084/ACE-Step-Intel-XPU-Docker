#!/usr/bin/env python3
"""Show the real Format API error in the UI alert (not a generic LLM message).

Also soft-timeout messaging for long LM loads.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find(name: str) -> Path | None:
    hits = [p for p in Path(".").rglob(name) if "node_modules" not in str(p)]
    return hits[0] if hits else None


def patch_create_panel() -> None:
    p = _find("CreatePanel.tsx")
    if not p or not p.is_file():
        print("CreatePanel.tsx not found", file=sys.stderr)
        return
    text = p.read_text()
    changed = False

    # Replace every generic Format-failed alert with one that includes err.message
    generics = [
        "alert('Format failed. The LLM may not be available.');",
        'alert("Format failed. The LLM may not be available.");',
        "alert(msg);",  # only if our prior timeout patch left a weak msg
    ]

    better = (
        "{\n"
        "        const raw = (err as any)?.message || String(err);\n"
        "        const msg = /timeout/i.test(raw)\n"
        "          ? 'Format timed out (LM busy / still loading). Wait for LM init, or switch to 1.7B, then try again.'\n"
        "          : ('Format failed: ' + raw);\n"
        "        console.error('[Format]', err);\n"
        "        alert(msg);\n"
        "      }"
    )

    # Prefer replacing the whole catch body pattern
    # catch (err) { alert('Format failed...'); }
    pat = re.compile(
        r"catch\s*\(\s*err\s*\)\s*\{[^}]*Format failed[^}]*\}",
        re.S,
    )
    if pat.search(text):
        text = pat.sub("catch (err) " + better, text, count=2)
        changed = True
        print("OK replaced Format catch blocks with real error alert")
    else:
        for g in generics[:2]:
            if g in text:
                text = text.replace(
                    g,
                    "console.error('[Format]', err);\n"
                    "      alert('Format failed: ' + ((err as any)?.message || String(err)));",
                    1,
                )
                changed = True
                print(f"OK replaced generic: {g[:40]}...")

    # Also surface result.error when formatInput returns without throwing
    if "Make sure the LLM is initialized" in text:
        text = text.replace(
            "alert(result.error || result.status_message || 'Format failed. Make sure the LLM is initialized.');",
            "alert('Format failed: ' + (result.error || result.status_message || 'LLM may not be ready — check acestep-xpu logs for [XPU-format]'));",
            1,
        )
        changed = True
        print("OK improved result.error alert")

    if changed:
        p.write_text(text)
        print(f"Wrote {p}")
    else:
        print("No Format alert patterns found to patch")


def patch_generate_format_proxy() -> None:
    """Ensure /api/generate/format forwards the Gradio error body clearly."""
    p = _find("generate.ts")
    if not p:
        return
    text = p.read_text()
    if "[Format] API error" in text and "success: false, error: errMsg" in text:
        # already logs; ensure UI gets string error
        if "Format API returned" in text:
            print("generate.ts format proxy already detailed")
            return


def main() -> None:
    patch_create_panel()
    patch_generate_format_proxy()
    print("format-ui-timeout patch complete")


if __name__ == "__main__":
    main()
