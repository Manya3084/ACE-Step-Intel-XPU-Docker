#!/usr/bin/env python3
"""Persist last DiT (and LM) model after live /v1/init switch.

Writes into the mounted checkpoints volume so a container restart can
restore ACESTEP_CONFIG_PATH / ACESTEP_LM_MODEL_PATH from disk instead of
always booting acestep-v15-turbo.

Files (host ./checkpoints/):
  .last_dit_model
  .last_lm_model
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-LAST-MODEL]"

WRITE_HELPER = '''
def _xpu_persist_last_model(dit_name: str = "", lm_name: str = "") -> None:
    """[XPU-LAST-MODEL] Save last DiT/LM into checkpoints volume."""
    try:
        from pathlib import Path as _P
        base = _P("/app/checkpoints")
        base.mkdir(parents=True, exist_ok=True)
        if dit_name:
            (base / ".last_dit_model").write_text(str(dit_name).strip() + "\\n")
        if lm_name:
            (base / ".last_lm_model").write_text(str(lm_name).strip() + "\\n")
    except Exception as _e:
        try:
            from loguru import logger as _log
            _log.warning("[XPU-LAST-MODEL] persist failed: {}", _e)
        except Exception:
            pass
'''


def find_api_routes() -> list[Path]:
    hits = []
    for root in (Path("/app"), Path(".")):
        if not root.is_dir():
            continue
        hits.extend(root.rglob("api_routes.py"))
    # de-dupe
    seen = set()
    out = []
    for p in hits:
        k = str(p.resolve()) if p.exists() else str(p)
        if k not in seen and "node_modules" not in k:
            seen.add(k)
            out.append(p)
    return out


def patch_file(path: Path) -> bool:
    text = path.read_text()
    if MARKER in text and "_xpu_persist_last_model" in text:
        # Ensure call sites exist
        if "_xpu_persist_last_model(" in text:
            print(f"Already patched: {path}")
            return False

    changed = False

    if "_xpu_persist_last_model" not in text:
        # Insert helper near top after imports / logger
        m = re.search(r"^(from loguru import logger\s*\n)", text, re.M)
        if m:
            text = text[: m.end()] + WRITE_HELPER + text[m.end() :]
            changed = True
            print(f"OK helper inserted in {path}")
        else:
            # after first import block
            m2 = re.search(r"(^import .+\n)", text, re.M)
            if m2:
                # find end of consecutive imports
                pos = 0
                for m3 in re.finditer(
                    r"^(?:import |from ).+$\n", text, re.M
                ):
                    pos = m3.end()
                text = text[:pos] + WRITE_HELPER + text[pos:]
                changed = True
                print(f"OK helper after imports in {path}")
            else:
                print(f"WARN: could not insert helper in {path}", file=sys.stderr)

    # After successful DiT load log lines, persist
    # Patterns from live-dit-switch / upstream
    patterns = [
        (
            r'(logger\.info\(\s*[\n\s]*f?["\']\[v1/init\] DiT loaded: \{?loaded\}?["\']\s*\))',
            r'\1\n        _xpu_persist_last_model(dit_name=str(loaded))  # ' + MARKER,
        ),
        (
            r'(logger\.info\([^)]*DiT loaded:[^)]*\))',
            r'\1\n        _xpu_persist_last_model(dit_name=str(loaded) if "loaded" in dir() else "")  # '
            + MARKER,
        ),
    ]

    if "_xpu_persist_last_model(dit_name" not in text:
        # Prefer explicit success sites in _switch_dit_model_sync
        if 'DiT loaded:' in text and '_xpu_persist_last_model' in text:
            # inject after first DiT loaded log inside function
            text2, n = re.subn(
                r"(DiT loaded:[^\n]*\n)",
                r"\1        _xpu_persist_last_model(dit_name=str(loaded))  # "
                + MARKER
                + r"\n",
                text,
                count=2,
            )
            if n:
                text = text2
                changed = True
                print(f"OK persist call after DiT loaded ({n})")

        # Fallback: after assign loaded = ... model path success
        if "_xpu_persist_last_model(dit_name" not in text:
            # look for return dict with model name after switch
            m = re.search(
                r"([\"']model[\"']\s*:\s*loaded)",
                text,
            )
            if m:
                # find a nearby safe injection: before return {
                pass

            # Inject at end of _switch_dit_model_sync before final return that includes ui_config
            m = re.search(
                r"(def _switch_dit_model_sync\([\s\S]{0,8000}?)",
                text,
            )
            if m and "_xpu_persist_last_model(dit_name" not in text:
                # Before "return {" that has ui_config
                text3, n3 = re.subn(
                    r"(\n(\s+)return \{\s*\n\s*[\"'](?:ok|success|model))",
                    r"\n\2_xpu_persist_last_model("
                    r"dit_name=str(loaded) if 'loaded' in locals() else ''"
                    r")  # "
                    + MARKER
                    + r"\1",
                    text,
                    count=1,
                )
                if n3:
                    text = text3
                    changed = True
                    print("OK persist before return in switch")

    # LM switch persist if present
    if "init_llm" in text and "_xpu_persist_last_model" in text:
        if "_xpu_persist_last_model(lm_name" not in text and "lm_model_path" in text:
            text4, n4 = re.subn(
                r"(LM (?:loaded|initialized|re-?init)[^\n]*\n)",
                r"\1        _xpu_persist_last_model(lm_name=str(lm_model_path) if 'lm_model_path' in dir() else '')  # "
                + MARKER
                + r"\n",
                text,
                count=1,
            )
            if n4:
                text = text4
                changed = True
                print("OK LM persist call")

    if not changed and MARKER not in text:
        print(f"WARN: no changes applied to {path}", file=sys.stderr)
        return False

    path.write_text(text)
    print(f"Wrote {path}")
    return True


def main() -> None:
    paths = find_api_routes()
    if not paths:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)
    n = sum(1 for p in paths if patch_file(p))
    print(f"persist-last-model: {n} file(s) updated")


if __name__ == "__main__":
    main()
