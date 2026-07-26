#!/usr/bin/env python3
"""Persist last DiT/LM to /app/checkpoints/.last_* after every successful switch.

Entrypoint reads these and sets ACESTEP_CONFIG_PATH / ACESTEP_LM_MODEL_PATH.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-LAST-MODEL]"

HELPER = r'''
def _xpu_persist_last_model(dit_name: str = "", lm_name: str = "") -> None:
    """[XPU-LAST-MODEL] Save last DiT/LM into /app/checkpoints (host volume)."""
    try:
        from pathlib import Path as _P
        base = _P("/app/checkpoints")
        base.mkdir(parents=True, exist_ok=True)
        if dit_name and str(dit_name).strip():
            name = str(dit_name).strip()
            # normalize aliases
            aliases = {
                "1.5xl soft": "acestep-v15-xl-sft",
                "1.5xl-soft": "acestep-v15-xl-sft",
                "xl-soft": "acestep-v15-xl-sft",
                "soft": "acestep-v15-xl-sft",
                "1.5xl base": "acestep-v15-xl-base",
                "1.5xlb": "acestep-v15-xl-base",
            }
            key = name.lower()
            name = aliases.get(key, name)
            (base / ".last_dit_model").write_text(name + "\n")
            print(f"[XPU-LAST-MODEL] wrote .last_dit_model={name}")
        if lm_name and str(lm_name).strip():
            name = str(lm_name).strip()
            (base / ".last_lm_model").write_text(name + "\n")
            print(f"[XPU-LAST-MODEL] wrote .last_lm_model={name}")
    except Exception as _e:
        print(f"[XPU-LAST-MODEL] persist failed: {_e}")
'''


def patch_api_routes(path: Path) -> bool:
    text = path.read_text()
    changed = False

    # Always refresh helper body so alias fixes land on restart
    if "_xpu_persist_last_model" in text:
        text2 = re.sub(
            r"\ndef _xpu_persist_last_model\([\s\S]*?\n    except Exception as _e:[\s\S]*?print\(f\"\[XPU-LAST-MODEL\] persist failed:[\s\S]*?\)\n",
            "\n" + HELPER.strip() + "\n",
            text,
            count=1,
        )
        if text2 != text:
            text = text2
            changed = True
            print("OK refreshed _xpu_persist_last_model helper")
    else:
        if "from loguru import logger" in text:
            text = text.replace(
                "from loguru import logger",
                "from loguru import logger\n" + HELPER,
                1,
            )
        else:
            text = HELPER + "\n" + text
        changed = True
        print(f"OK helper in {path}")

    # DiT: persist after "DiT loaded" using loaded or model variable
    if "_xpu_persist_last_model(dit_name=" not in text or text.count("_xpu_persist_last_model(dit_name=") < 1:
        # Prefer explicit injection after DiT loaded log
        if "DiT loaded" in text and "_xpu_persist_last_model(dit_name=" not in text:
            lines = text.splitlines(keepends=True)
            out = []
            done = False
            for line in lines:
                out.append(line)
                if (
                    not done
                    and "DiT loaded" in line
                    and "logger" in line
                ):
                    indent = re.match(r"^(\s*)", line).group(1)
                    out.append(
                        f"{indent}try:\n"
                        f"{indent}    _xpu_persist_last_model(dit_name=str(loaded if 'loaded' in dir() else model))  # {MARKER}\n"
                        f"{indent}except Exception:\n"
                        f"{indent}    pass\n"
                    )
                    done = True
                    changed = True
                    print("OK DiT persist after DiT loaded")
            text = "".join(out)

    # Also persist when switch starts with target model name (more reliable)
    if "_xpu_persist_last_model(dit_name=str(model)" not in text:
        # common pattern in _switch_dit_model_sync
        for needle in (
            "Switching DiT:",
            "[v1/init] Switching DiT",
        ):
            if needle in text:
                # insert after the log line that mentions Switching DiT
                lines = text.splitlines(keepends=True)
                out = []
                done = False
                for line in lines:
                    out.append(line)
                    if not done and needle in line and "logger" in line:
                        indent = re.match(r"^(\s*)", line).group(1)
                        # try to persist `model` or `config_path` if in scope later on success only
                        # skip start-of-switch write — wait for success
                        done = True
                    out  # keep
                text = "".join(out)
                break

    # Success return path: loaded_model key
    if '"loaded_model"' in text and "_xpu_persist_last_model(dit_name=str(loaded)" not in text:
        text2, n = re.subn(
            r'("loaded_model"\s*:\s*loaded)',
            r'_xpu_persist_last_model(dit_name=str(loaded))  # '
            + MARKER
            + r'\n        \1',
            text,
            count=1,
        )
        if n:
            text = text2
            changed = True
            print("OK DiT persist near loaded_model")

    # LM persist
    if "_xpu_persist_last_model(lm_name=" not in text:
        if "LM loaded" in text:
            lines = text.splitlines(keepends=True)
            out = []
            done = False
            for line in lines:
                out.append(line)
                if not done and "LM loaded" in line and "logger" in line:
                    indent = re.match(r"^(\s*)", line).group(1)
                    out.append(
                        f"{indent}_xpu_persist_last_model(lm_name=str(loaded))  # {MARKER}\n"
                    )
                    done = True
                    changed = True
                    print("OK LM persist after LM loaded")
            text = "".join(out)
        if "_xpu_persist_last_model(lm_name=" not in text and '"loaded_lm_model"' in text:
            text = text.replace(
                '"loaded_lm_model": loaded',
                '_xpu_persist_last_model(lm_name=str(loaded))  # '
                + MARKER
                + '\n        "loaded_lm_model": loaded',
                1,
            )
            changed = True
            print("OK LM persist near loaded_lm_model")

    if changed:
        path.write_text(text)
        print(f"Wrote {path}")
        return True
    print(f"No change: {path}")
    return False


def main() -> None:
    paths = []
    for root in (Path("/app"), Path(".")):
        if root.is_dir():
            paths.extend(root.rglob("api_routes.py"))
    seen = set()
    files = []
    for p in paths:
        k = str(p.resolve()) if p.exists() else str(p)
        if "node_modules" in k:
            continue
        if k not in seen:
            seen.add(k)
            files.append(p)
    if not files:
        print("api_routes.py not found", file=sys.stderr)
        sys.exit(1)
    n = sum(1 for p in files if patch_api_routes(p))
    print(f"persist-last-model: {n} file(s) updated")


if __name__ == "__main__":
    main()
