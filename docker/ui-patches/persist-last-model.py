#!/usr/bin/env python3
"""Persist last DiT/LM after successful live switch to checkpoints volume."""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-LAST-MODEL]"

HELPER = '''
def _xpu_persist_last_model(dit_name: str = "", lm_name: str = "") -> None:
    """[XPU-LAST-MODEL] Save last DiT/LM into /app/checkpoints (host volume)."""
    try:
        from pathlib import Path as _P
        base = _P("/app/checkpoints")
        base.mkdir(parents=True, exist_ok=True)
        if dit_name and str(dit_name).strip():
            (base / ".last_dit_model").write_text(str(dit_name).strip() + "\\n")
        if lm_name and str(lm_name).strip():
            (base / ".last_lm_model").write_text(str(lm_name).strip() + "\\n")
    except Exception as _e:
        try:
            from loguru import logger as _lg
            _lg.warning("[XPU-LAST-MODEL] persist failed: {}", _e)
        except Exception:
            pass
'''


def main() -> None:
    paths = []
    for root in (Path("/app"), Path(".")):
        if root.is_dir():
            paths.extend(root.rglob("api_routes.py"))
    seen = set()
    files = []
    for p in paths:
        k = str(p.resolve()) if p.exists() else str(p)
        if k not in seen and "node_modules" not in k:
            seen.add(k)
            files.append(p)
    if not files:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)

    for path in files:
        text = path.read_text()
        changed = False

        if "_xpu_persist_last_model" not in text:
            if "from loguru import logger" in text:
                text = text.replace(
                    "from loguru import logger",
                    "from loguru import logger\n" + HELPER,
                    1,
                )
            else:
                text = HELPER + "\n" + text
            changed = True
            print(f"OK helper: {path}")

        # After DiT loaded success log (several formats)
        if "_xpu_persist_last_model(dit_name" not in text:
            for pat, repl in [
                (
                    r'(logger\.info\([\s\S]*?\[v1/init\] DiT loaded:[\s\S]*?\))',
                    r"\1\n        _xpu_persist_last_model(dit_name=str(loaded))  # "
                    + MARKER,
                ),
                (
                    r'(\[[v1/init\] DiT loaded: \{loaded\})',
                    None,  # skip
                ),
            ]:
                if repl is None:
                    continue
                text2, n = re.subn(pat, repl, text, count=2)
                if n:
                    text = text2
                    changed = True
                    print(f"OK dit persist via log ({n})")
                    break
            if "_xpu_persist_last_model(dit_name" not in text:
                # Inject near "DiT loaded" string assignment flow
                if "DiT loaded:" in text:
                    text = text.replace(
                        "DiT loaded:",
                        "DiT loaded:",
                        1,
                    )
                    # After line containing DiT loaded logger call - append next line
                    lines = text.splitlines(keepends=True)
                    out = []
                    done = False
                    for line in lines:
                        out.append(line)
                        if (
                            not done
                            and "DiT loaded" in line
                            and "logger" in line
                            and "_xpu_persist_last_model" not in line
                        ):
                            indent = re.match(r"^(\s*)", line).group(1)
                            out.append(
                                f"{indent}_xpu_persist_last_model(dit_name=str(loaded))  # {MARKER}\n"
                            )
                            done = True
                            changed = True
                            print("OK dit persist after DiT loaded line")
                    text = "".join(out)

        if "_xpu_persist_last_model(dit_name" not in text:
            # last resort: any successful switch return with loaded variable
            text2, n = re.subn(
                r"(\n(\s+)\"model\":\s*loaded,)",
                r"\n\2_xpu_persist_last_model(dit_name=str(loaded))  # "
                + MARKER
                + r"\1",
                text,
                count=1,
            )
            if n:
                text = text2
                changed = True
                print("OK dit persist before model:loaded")

        if changed:
            path.write_text(text)
            print(f"Wrote {path}")
        else:
            print(f"No change: {path}")

    print("persist-last-model complete")


if __name__ == "__main__":
    main()
