#!/usr/bin/env python3
"""Wire standalone format routes into acestep_v15_pipeline.py safely.

1. Copy xpu_format_routes.py into the acestep package
2. Strip any previous broken _xpu_register_format_input from the pipeline
3. Ensure a single clean call after setup_api_routes
4. ast.parse the pipeline — fail the build if syntax is broken
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path


def _strip_old_helper(text: str) -> str:
    """Remove any inlined _xpu_register_format_input function (broken or not)."""
    marker = "def _xpu_register_format_input"
    while marker in text:
        start = text.find(marker)
        # Walk by indent to end of function
        nl = text.find("\n", start)
        if nl < 0:
            text = text[:start]
            break
        i = nl + 1
        n = len(text)
        while i < n:
            nl = text.find("\n", i)
            line = text[i:] if nl < 0 else text[i:nl]
            line_end = n if nl < 0 else nl + 1
            stripped = line.lstrip("\r")
            if stripped.strip() == "" or stripped.lstrip().startswith("#"):
                i = line_end
                continue
            if line.startswith(" ") or line.startswith("\t"):
                i = line_end
                continue
            # column-0 → end
            text = text[:start] + text[i:]
            break
        else:
            text = text[:start]
            break
    # Drop old one-liner registrations
    text = re.sub(
        r"^[ \t]*_xpu_register_format_input\([^\n]*\)\s*\n",
        "",
        text,
        flags=re.M,
    )
    return text


def main() -> None:
    root = Path("/app")
    src = root / "docker" / "ui-patches" / "xpu_format_routes.py"
    if not src.is_file():
        # host-side path during dev
        src = Path(__file__).resolve().parent / "xpu_format_routes.py"
    if not src.is_file():
        print(f"xpu_format_routes.py not found at {src}", file=sys.stderr)
        sys.exit(1)

    # Install into package
    pkg_dirs = list(root.rglob("acestep"))
    pkg_dirs = [p for p in pkg_dirs if p.is_dir() and (p / "__init__.py").exists()]
    if not pkg_dirs:
        # fallback
        dest_dir = root / "acestep"
        dest_dir.mkdir(parents=True, exist_ok=True)
        pkg_dirs = [dest_dir]

    for d in pkg_dirs:
        dest = d / "xpu_format_routes.py"
        shutil.copy2(src, dest)
        print(f"Installed {dest}")

    pipelines = list(root.rglob("acestep_v15_pipeline.py"))
    if not pipelines:
        print("acestep_v15_pipeline.py not found", file=sys.stderr)
        sys.exit(1)

    for path in pipelines:
        text = path.read_text()
        text = _strip_old_helper(text)

        if "register_format_routes(demo, llm_handler)" not in text:
            pat = re.compile(r"(setup_api_routes\([^\n]*\))")
            m = pat.search(text)
            if not m:
                print(f"setup_api_routes not found in {path}", file=sys.stderr)
                sys.exit(1)
            injection = (
                m.group(1)
                + "\n            from acestep.xpu_format_routes import register_format_routes"
                + "\n            register_format_routes(demo, llm_handler)"
            )
            text = pat.sub(injection, text, count=1)
            print(f"Wired register_format_routes into {path}")
        else:
            print(f"register_format_routes already wired: {path}")

        # Syntax check — fail build hard if broken
        try:
            ast.parse(text)
        except SyntaxError as exc:
            path.write_text(text)  # still write for debugging
            print(f"SYNTAX ERROR in {path}: {exc}", file=sys.stderr)
            sys.exit(1)

        path.write_text(text)
        print(f"OK syntax: {path}")

    print("wire-format-routes complete")


if __name__ == "__main__":
    main()
