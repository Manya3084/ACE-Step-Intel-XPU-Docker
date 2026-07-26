#!/usr/bin/env python3
"""Point ace-step-ui Format proxy at /xpu/format_input (avoids Gradio 422 clash)."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    files = [
        p
        for p in Path(".").rglob("generate.ts")
        if "node_modules" not in str(p) and "routes" in str(p)
    ]
    if not files:
        files = list(Path(".").rglob("generate.ts"))
        files = [p for p in files if "node_modules" not in str(p)]
    if not files:
        print("generate.ts not found", file=sys.stderr)
        sys.exit(1)

    for path in files:
        text = path.read_text()
        orig = text
        # Prefer dedicated XPU path
        text = text.replace(
            "${ACESTEP_API_URL}/format_input",
            "${ACESTEP_API_URL}/xpu/format_input",
        )
        text = text.replace(
            "${ACESTEP_API_URL}/format_lyrics",
            "${ACESTEP_API_URL}/xpu/format_input",
        )
        text = text.replace(
            "/format_input",
            "/xpu/format_input",
        )
        # Don't double-prefix
        text = text.replace("/xpu/xpu/format_input", "/xpu/format_input")
        # Better error stringify for arrays
        if "JSON.stringify(errMsg)" not in text and "Format API returned" in text:
            text = text.replace(
                "const errMsg = apiData.error || apiData.detail || `Format API returned ${apiRes.status}`;",
                "const errRaw = apiData.error || apiData.detail || `Format API returned ${apiRes.status}`;\n"
                "    const errMsg = typeof errRaw === 'string' ? errRaw : JSON.stringify(errRaw);",
                1,
            )
        if text != orig:
            path.write_text(text)
            print(f"OK format proxy -> /xpu/format_input in {path}")
        else:
            print(f"No change: {path}")

    print("format-proxy-xpu-path complete")


if __name__ == "__main__":
    main()
