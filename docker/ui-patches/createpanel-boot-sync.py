#!/usr/bin/env python3
"""On CreatePanel mount: sync backend LM/DiT to localStorage selection.

UI may show 4B while server booted 1.7B. After load, POST switch-lm / switch-dit
once so Format and generation see the same models.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "[XPU-BOOT-SYNC]"

BOOT_EFFECT = '''
  // [XPU-BOOT-SYNC] Align Gradio LM/DiT with sticky UI selection once on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const lm = (typeof localStorage !== 'undefined' && localStorage.getItem('ace-lmModel')) || lmModel;
        const dit = (typeof localStorage !== 'undefined' && localStorage.getItem('ace-model')) || selectedModel;
        if (lm && String(lm).includes('4B') || (lm && String(lm).includes('5Hz-lm'))) {
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


def main() -> None:
    hits = list(Path(".").rglob("CreatePanel.tsx"))
    hits = [p for p in hits if "node_modules" not in str(p)]
    if not hits:
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    path = hits[0]
    text = path.read_text()
    if MARKER in text:
        print("boot-sync already present")
        return

    # Insert after first useEffect or after lmModel state
    if "const [lmModel" in text:
        # find a good spot: after all useState, before first useEffect
        m = re.search(r"\n  useEffect\(", text)
        if m:
            text = text[: m.start()] + "\n" + BOOT_EFFECT + text[m.start() :]
        else:
            text = text + "\n" + BOOT_EFFECT
        path.write_text(text)
        print(f"OK boot-sync in {path}")
    else:
        print("WARN: lmModel state not found", file=sys.stderr)

    # Default LM dropdown to 1.7B if upstream hardcodes 4B without localStorage
    text = path.read_text()
    for old in (
        "useState('acestep-5Hz-lm-4B')",
        'useState("acestep-5Hz-lm-4B")',
        "useState('4B')",
    ):
        if old in text and "ace-lmModel" not in text[text.find(old) - 80 : text.find(old)]:
            # only if not already reading localStorage
            pass
    # Prefer localStorage with 1.7B fallback
    if "localStorage.getItem('ace-lmModel')" not in text and "ace-lmModel" in text:
        pass  # already sticky
    elif "const [lmModel, setLmModel] = useState(" in text:
        text2 = re.sub(
            r"const \[lmModel, setLmModel\] = useState\(([^)]+)\)",
            "const [lmModel, setLmModel] = useState(() => "
            "(typeof localStorage !== 'undefined' && localStorage.getItem('ace-lmModel')) "
            "|| 'acestep-5Hz-lm-1.7B')",
            text,
            count=1,
        )
        if text2 != text:
            path.write_text(text2)
            print("OK lmModel default 1.7B with localStorage")

    print("createpanel-boot-sync complete")


if __name__ == "__main__":
    main()
