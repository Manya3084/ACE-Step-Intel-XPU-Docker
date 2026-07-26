#!/usr/bin/env python3
"""On CreatePanel mount: sync backend LM/DiT to localStorage selection.

Also normalizes lmModel useState to a single valid initializer (repairs
double-patch from sticky + boot-sync)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-BOOT-SYNC]"

GOOD_LM_STATE = (
    "const [lmModel, setLmModel] = useState(() => "
    "(typeof localStorage !== 'undefined' && localStorage.getItem('ace-lmModel')) "
    "|| 'acestep-5Hz-lm-1.7B');"
)

BOOT_EFFECT = '''
  // [XPU-BOOT-SYNC] Align Gradio LM/DiT with sticky UI selection once on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const lm =
          (typeof localStorage !== 'undefined' && localStorage.getItem('ace-lmModel')) ||
          lmModel ||
          '';
        const dit =
          (typeof localStorage !== 'undefined' && localStorage.getItem('ace-model')) ||
          selectedModel ||
          '';
        if (lm) {
          const r = await fetch('/api/generate/switch-lm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lm_model_path: lm }),
          });
          const d = await r.json().catch(() => ({}));
          if (!cancelled) console.log('[boot-sync LM]', d.loaded_lm_model || d.message || r.status);
        }
        if (dit && String(dit).startsWith('acestep-')) {
          const r2 = await fetch('/api/generate/switch-dit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: dit }),
          });
          const d2 = await r2.json().catch(() => ({}));
          if (!cancelled) console.log('[boot-sync DiT]', d2.loaded_model || d2.message || r2.status);
        }
      } catch (e) {
        console.warn('[boot-sync]', e);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
'''


def repair_lm_model_state(text: str) -> str:
    """Replace any lmModel useState (including broken double-patch) with one good line."""
    # Broken form from stacking two patches:
    # useState(() => ...1.7B') => {
    # return localStorage...0.6B';
    # });
    broken = re.compile(
        r"const \[lmModel, setLmModel\] = useState\(\(\) =>[\s\S]*?\}\);",
        re.M,
    )
    if broken.search(text):
        text = broken.sub(GOOD_LM_STATE, text, count=1)
        print("Repaired broken/multi-line lmModel useState")
        return text

    # Any other useState for lmModel
    simple = re.compile(
        r"const \[lmModel, setLmModel\] = useState\([^;]*\);",
        re.M,
    )
    if simple.search(text):
        text = simple.sub(GOOD_LM_STATE, text, count=1)
        print("Normalized lmModel useState")
    return text


def main() -> None:
    hits = [p for p in Path(".").rglob("CreatePanel.tsx") if "node_modules" not in str(p)]
    if not hits:
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    path = hits[0]
    text = path.read_text()

    text = repair_lm_model_state(text)

    if MARKER not in text:
        m = re.search(r"\n  useEffect\(", text)
        if m:
            text = text[: m.start()] + "\n" + BOOT_EFFECT + text[m.start() :]
        else:
            text = text + "\n" + BOOT_EFFECT
        print(f"OK boot-sync effect in {path}")
    else:
        print("boot-sync effect already present")

    path.write_text(text)
    print("createpanel-boot-sync complete")


if __name__ == "__main__":
    main()
