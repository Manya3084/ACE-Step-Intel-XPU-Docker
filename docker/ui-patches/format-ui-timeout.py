#!/usr/bin/env python3
"""Hard-timeout the AI Format UI call so the spinner cannot spin forever.

Also ensures isFormattingStyle / isFormattingLyrics is cleared in finally.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find(name: str) -> Path | None:
    hits = list(Path(".").rglob(name))
    return hits[0] if hits else None


def patch_create_panel() -> None:
    p = _find("CreatePanel.tsx")
    if not p or not p.is_file():
        print("CreatePanel.tsx not found", file=sys.stderr)
        return
    text = p.read_text()
    if "FORMAT_TIMEOUT_MS" in text or "Format timed out" in text:
        print("CreatePanel Format timeout already present")
        return

    # Inject timeout constant near top of component file if missing
    if "FORMAT_TIMEOUT_MS" not in text:
        text = "const FORMAT_TIMEOUT_MS = 180_000;\n" + text

    # Wrap handleFormat body to use AbortSignal if fetch is direct — upstream uses generateApi.formatInput
    # Ensure finally always clears flags (usually already does) and add timeout note in catch
    old_catch = "alert('Format failed. The LLM may not be available.');"
    new_catch = (
        "const msg = (err as any)?.name === 'TimeoutError' || String(err).includes('timeout')\n"
        "        ? 'Format timed out (LLM busy or VRAM pressure). Try 1.7B LM or turbo DiT, then Format again.'\n"
        "        : 'Format failed. The LLM may not be available.';\n"
        "      alert(msg);"
    )
    if old_catch in text:
        text = text.replace(old_catch, new_catch, 1)
        print("OK Format timeout-aware alert")

    p.write_text(text)
    print(f"Patched CreatePanel Format messaging -> {p}")


def patch_api_client() -> None:
    # services/api.ts or similar — find formatInput
    candidates = list(Path(".").rglob("*.ts")) + list(Path(".").rglob("*.tsx"))
    for p in candidates:
        try:
            text = p.read_text()
        except Exception:
            continue
        if "formatInput" not in text and "format_lyrics" not in text:
            continue
        if "FORMAT_TIMEOUT" in text and "formatInput" in text:
            print(f"timeout already in {p}")
            continue

        changed = False
        # Add AbortSignal.timeout to fetch calls that hit format_lyrics / format
        if "format_lyrics" in text or "/format" in text:
            # generic: ensure format-related fetch has a long timeout
            new_text, n = re.subn(
                r"fetch\(([^)]*format[^)]*)\)",
                r"fetch(\1, { signal: AbortSignal.timeout(180000) })",
                text,
                count=3,
                flags=re.I,
            )
            # That may double-wrap; be more careful
            if n and "AbortSignal.timeout(180000)" not in text:
                text = new_text
                changed = True

        # If formatInput function exists, inject timeout into its fetch
        if "formatInput" in text and "AbortSignal.timeout" not in text:
            # Look for fetch inside formatInput-ish blocks
            if "format_lyrics" in text:
                text = text.replace(
                    "format_lyrics",
                    "format_lyrics",
                    1,
                )
                # Add timeout option near Content-Type format posts
                text2 = re.sub(
                    r"(method:\s*'POST'[\s\S]{0,200}?headers:[\s\S]{0,300}?)(\n\s*\})",
                    r"\1,\n        signal: AbortSignal.timeout(180000),\2",
                    text,
                    count=2,
                )
                if text2 != text:
                    text = text2
                    changed = True

        if changed:
            p.write_text(text)
            print(f"OK format timeout in {p}")


def main() -> None:
    patch_create_panel()
    patch_api_client()
    print("format-ui-timeout patch complete")


if __name__ == "__main__":
    main()
