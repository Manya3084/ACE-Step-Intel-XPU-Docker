#!/usr/bin/env python3
"""Apply full DiT-type guidance profile in CreatePanel when model changes.

When user picks turbo / base / sft / XL in ace-step-ui, apply matching
defaults so UI state matches backend model-type guidance (steps, ADG, etc.).

XPU: ADG always forced off (apg_forward kernel gap on Arc).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find_create_panel() -> Path | None:
    for c in (
        Path("components/CreatePanel.tsx"),
        Path("src/components/CreatePanel.tsx"),
    ):
        if c.is_file():
            return c
    hits = list(Path(".").rglob("CreatePanel.tsx"))
    return hits[0] if hits else None


PROFILE_HELPER = r'''
  // [XPU-DIT-PROFILE] full guidance profile per DiT family (matches Gradio model_config)
  const applyDitGuidanceProfile = useCallback((modelId: string) => {
    if (!modelId) return;
    const id = modelId.toLowerCase();
    const isTurbo = id.includes('turbo');
    const isSft = id.includes('sft') && !isTurbo;
    const isBase = id.includes('base') && !isTurbo && !isSft;
    // XPU: never auto-enable ADG — apg_forward fails on Arc
    if (typeof setUseAdg === 'function') setUseAdg(false);
    if (isTurbo) {
      if (typeof setInferenceSteps === 'function') setInferenceSteps(8);
    } else if (isSft || isBase) {
      if (typeof setInferenceSteps === 'function') setInferenceSteps(50);
    } else {
      if (typeof setInferenceSteps === 'function') setInferenceSteps(32);
    }
    if (!isTurbo && typeof setGuidanceScale === 'function') {
      setGuidanceScale(7.0);
    }
  }, []);
'''


def main() -> None:
    p = _find_create_panel()
    if p is None:
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)

    text = p.read_text()
    original = text

    if "[XPU-DIT-PROFILE]" in text and "applyDitGuidanceProfile" in text:
        print("Dit profile helper already present")
    else:
        if "const isTurboModel = (modelId: string): boolean => {" in text:
            m = re.search(
                r"(const isTurboModel = \(modelId: string\): boolean => \{\s*"
                r"return modelId\.includes\('turbo'\);\s*\};)",
                text,
            )
            if m:
                text = text[: m.end()] + "\n" + PROFILE_HELPER + text[m.end() :]
                print("OK inserted applyDitGuidanceProfile")
            else:
                print("WARN: isTurboModel pattern mismatch", file=sys.stderr)
        else:
            print("WARN: isTurboModel not found", file=sys.stderr)

    old_select_body = """  const selectDitModel = useCallback((modelId: string) => {
    if (!modelId) return;
    setSelectedModel(modelId);
    localStorage.setItem('ace-model', modelId);
    if (!isTurboModel(modelId)) {
      setInferenceSteps(20);
      setUseAdg(true);
    }
    setShowModelMenu(false);
  }, []);"""

    new_select_body = """  const selectDitModel = useCallback((modelId: string) => {
    if (!modelId) return;
    setSelectedModel(modelId);
    localStorage.setItem('ace-model', modelId);
    applyDitGuidanceProfile(modelId);
    setShowModelMenu(false);
  }, [applyDitGuidanceProfile]);"""

    if old_select_body in text:
        text = text.replace(old_select_body, new_select_body, 1)
        print("OK selectDitModel uses applyDitGuidanceProfile")
    elif "applyDitGuidanceProfile(modelId)" in text:
        print("selectDitModel already calls profile")
    else:
        if "selectDitModel" in text and "setInferenceSteps(20)" in text:
            text2 = re.sub(
                r"if \(!isTurboModel\(modelId\)\) \{\s*"
                r"setInferenceSteps\(\d+\);\s*"
                r"(?://[^\n]*\n\s*)?"
                r"setUseAdg\((?:true|false)\)(?:\s*/\*[^*]*\*/)?;\s*"
                r"\}",
                "applyDitGuidanceProfile(modelId);",
                text,
                count=1,
            )
            if text2 != text:
                text = text2
                print("OK replaced non-turbo if-block with applyDitGuidanceProfile")
            else:
                print("WARN: could not wire selectDitModel profile", file=sys.stderr)

    if "setUseAdg(true)" in text:
        text = text.replace("setUseAdg(true)", "setUseAdg(false) /* XPU: ADG off */")
        print("OK remaining setUseAdg(true) → false")

    if text != original:
        p.write_text(text)
        print(f"Wrote {p}")
    else:
        print(f"No CreatePanel changes: {p}")


if __name__ == "__main__":
    main()
