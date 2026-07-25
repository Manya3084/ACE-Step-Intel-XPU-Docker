#!/usr/bin/env python3
"""Ensure get_gpu_config is importable in acestep_v15_pipeline.py.

Do NOT insert a column-0 import inside an existing try: block — that caused:
  SyntaxError: expected 'except' or 'finally' block (line 52)

Upstream already has either:
  from .gpu_config import get_gpu_config
or
  from acestep.gpu_config import get_gpu_config
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def _has_get_gpu_config_import(text: str) -> bool:
    if "get_gpu_config" not in text:
        return False
    # Relative or absolute import forms used by ACE-Step
    markers = (
        "from .gpu_config import",
        "from acestep.gpu_config import",
        "import acestep.gpu_config",
    )
    if not any(m in text for m in markers):
        return False
    # Prefer real parse when possible
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # File may already be broken; still treat marker presence as OK for import
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("gpu_config", "acestep.gpu_config") or mod.endswith(
                ".gpu_config"
            ):
                for alias in node.names:
                    if alias.name == "get_gpu_config" or alias.name == "*":
                        return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "gpu_config" in (alias.name or ""):
                    return True
    return "get_gpu_config" in text and any(m in text for m in markers)


def main() -> None:
    paths = list(Path("/app").rglob("acestep_v15_pipeline.py"))
    if not paths:
        paths = list(Path(".").rglob("acestep_v15_pipeline.py"))
    if not paths:
        print("acestep_v15_pipeline.py not found", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        text = path.read_text()

        # If already broken, do not make it worse with a blind insert
        try:
            ast.parse(text)
            syntax_ok = True
        except SyntaxError as exc:
            syntax_ok = False
            print(f"WARNING: {path} has SyntaxError before fix: {exc}")

        if _has_get_gpu_config_import(text):
            print(f"get_gpu_config import OK: {path}")
            continue

        if not syntax_ok:
            print(
                f"Refusing to inject import into syntactically invalid {path}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Safe inject: only at module top, after docstring / future imports
        line = "from acestep.gpu_config import get_gpu_config  # [XPU-import-fix]\n"
        # Find end of leading docstring
        insert_at = 0
        if text.startswith('"""') or text.startswith("'''"):
            q = text[:3]
            end = text.find(q, 3)
            if end > 0:
                insert_at = end + 3
                if insert_at < len(text) and text[insert_at] == "\n":
                    insert_at += 1

        # Skip __future__ imports
        rest = text[insert_at:]
        while rest.startswith("from __future__"):
            nl = rest.find("\n")
            if nl < 0:
                break
            insert_at += nl + 1
            rest = text[insert_at:]

        text = text[:insert_at] + line + text[insert_at:]
        try:
            ast.parse(text)
        except SyntaxError as exc:
            print(f"Inject would break {path}: {exc}", file=sys.stderr)
            sys.exit(1)
        path.write_text(text)
        print(f"Added get_gpu_config import at module top: {path}")

    print("fix-pipeline-imports complete")


if __name__ == "__main__":
    main()
