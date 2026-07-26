#!/usr/bin/env python3
"""Live-switch DiT when user picks a model in Create panel (incl. mobile + XL).

Problems fixed:
1. refreshModels() always set selectedModel = backend is_active → snapped back to 1.5T
2. Mobile taps often never fired menu onClick → no switch-dit / no console log
3. Only mousedown outside-close; touch path incomplete

Approach:
- POST /api/generate/switch-dit still in generate.ts
- CreatePanel: selectModel() + useEffect on selectedModel → switch-dit
- refreshModels only updates badges, does not overwrite user selection
- Menu items: onPointerUp + onClick; outside: mousedown + touchstart
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find(name: str, *hints: str) -> Path | None:
    for c in Path(".").rglob(name):
        s = str(c)
        if all(h in s for h in hints):
            return c
    hits = list(Path(".").rglob(name))
    return hits[0] if hits else None


def patch_generate_ts() -> None:
    p = _find("generate.ts", "routes") or Path("server/src/routes/generate.ts")
    if not p.is_file():
        print("generate.ts not found", file=sys.stderr)
        sys.exit(1)
    text = p.read_text()
    if "/switch-dit" in text:
        print("switch-dit endpoint already present")
        return

    endpoint = r'''
// POST /api/generate/switch-dit — live-switch DiT via Gradio /v1/init
router.post('/switch-dit', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    let model = String(
      body.model || body.ditModel || body.dit_model || body.config_path || ''
    ).trim();
    if (!model) {
      res.status(400).json({ error: 'model is required' });
      return;
    }
    if (!model.startsWith('acestep-v15-')) {
      res.status(400).json({ error: `Unsupported DiT model: ${model}` });
      return;
    }

    const ACESTEP_API_URL = config.acestep.apiUrl;
    console.log(`[switch-dit] POST ${ACESTEP_API_URL}/v1/init model=${model}`);
    const apiRes = await fetch(`${ACESTEP_API_URL}/v1/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, init_llm: false }),
      signal: AbortSignal.timeout(600_000),
    });
    const apiData = await apiRes.json() as any;
    if (!apiRes.ok || (apiData.code != null && apiData.code !== 200)) {
      const errMsg = apiData.error || apiData.detail || `switch-dit returned ${apiRes.status}`;
      console.error('[switch-dit] failed:', errMsg);
      res.status(500).json({ success: false, error: errMsg });
      return;
    }
    const data = apiData.data || apiData;
    res.json({
      success: true,
      loaded_model: data.loaded_model || model,
      switched: data.switched ?? true,
      message: data.message || `DiT ${model} ready`,
      models: data.models,
      default_model: data.default_model || data.loaded_model || model,
    });
  } catch (error: any) {
    console.error('[switch-dit] error:', error);
    res.status(500).json({ success: false, error: error?.message || String(error) });
  }
});
'''

    if "router.post('/switch-lm'" in text:
        text = text.replace(
            "router.post('/switch-lm'",
            endpoint.strip() + "\n\nrouter.post('/switch-lm'",
            1,
        )
    elif "router.get('/models'" in text:
        text = text.replace(
            "router.get('/models'",
            endpoint.strip() + "\n\nrouter.get('/models'",
            1,
        )
    elif "export default router" in text:
        text = text.replace(
            "export default router",
            endpoint.strip() + "\n\nexport default router",
            1,
        )
    else:
        text = text.rstrip() + "\n" + endpoint + "\n"

    p.write_text(text)
    print(f"OK added POST /switch-dit to {p}")


def patch_create_panel() -> None:
    p = _find("CreatePanel.tsx") or Path("components/CreatePanel.tsx")
    if not p.is_file():
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    text = p.read_text()
    original = text

    # --- XL display names ---
    if "'acestep-v15-xl-turbo'" not in text or "1.5XL" not in text:
        old_map = """    const mapping: Record<string, string> = {
      'acestep-v15-base': '1.5B',
      'acestep-v15-sft': '1.5S',
      'acestep-v15-turbo-shift1': '1.5TS1',
      'acestep-v15-turbo-shift3': '1.5TS3',
      'acestep-v15-turbo-continuous': '1.5TC',
      'acestep-v15-turbo': '1.5T',
    };"""
        new_map = """    const mapping: Record<string, string> = {
      'acestep-v15-base': '1.5B',
      'acestep-v15-sft': '1.5S',
      'acestep-v15-turbo-shift1': '1.5TS1',
      'acestep-v15-turbo-shift3': '1.5TS3',
      'acestep-v15-turbo-continuous': '1.5TC',
      'acestep-v15-turbo': '1.5T',
      'acestep-v15-xl-turbo': '1.5XL-T',
      'acestep-v15-xl-sft': '1.5XL-S',
      'acestep-v15-xl-base': '1.5XL-B',
    };"""
        if old_map in text:
            text = text.replace(old_map, new_map, 1)
            print("OK XL display names")

    # --- refreshModels: do NOT overwrite user selection ---
    old_refresh_sync = """          setFetchedModels(models);
          // Always sync to the backend's active model
          const active = models.find((m: any) => m.is_active);
          if (active) {
            setSelectedModel(active.name);
            localStorage.setItem('ace-model', active.name);
          }"""
    new_refresh_sync = """          setFetchedModels(models);
          // Do NOT force selectedModel to backend is_active — that snapped
          // mobile (and desktop) back to 1.5T after every refresh/generate.
          // Keep localStorage / user pick; badges still show Active/Ready."""
    if old_refresh_sync in text:
        text = text.replace(old_refresh_sync, new_refresh_sync, 1)
        print("OK refreshModels no longer overwrites selection")
    elif "Always sync to the backend's active model" in text:
        text = re.sub(
            r"// Always sync to the backend's active model\s*"
            r"const active = models\.find\(\(m: any\) => m\.is_active\);\s*"
            r"if \(active\) \{\s*"
            r"setSelectedModel\(active\.name\);\s*"
            r"localStorage\.setItem\('ace-model', active\.name\);\s*"
            r"\}",
            "// [XPU] keep user selection; badges come from fetchedModels",
            text,
            count=1,
        )
        print("OK refreshModels overwrite removed (regex)")

    # --- click-outside: also touchstart (mobile) ---
    old_outside = """    const handleClickOutside = (event: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
        setShowModelMenu(false);
      }
    };

    if (showModelMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }"""
    new_outside = """    const handleClickOutside = (event: Event) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
        setShowModelMenu(false);
      }
    };

    if (showModelMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('touchstart', handleClickOutside, { passive: true });
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
        document.removeEventListener('touchstart', handleClickOutside);
      };
    }"""
    if old_outside in text:
        text = text.replace(old_outside, new_outside, 1)
        print("OK mobile touch outside-close")

    # --- selectModel helper + useEffect switch (idempotent markers) ---
    if "[XPU-DIT-SELECT]" not in text:
        # Insert after isTurboModel definition
        turbo_fn = "  const isTurboModel = (modelId: string): boolean => {\n    return modelId.includes('turbo');\n  };"
        helper = '''  const isTurboModel = (modelId: string): boolean => {
    return modelId.includes('turbo');
  };

  // [XPU-DIT-SELECT] single path for desktop click + mobile pointer/touch
  const selectDitModel = useCallback((modelId: string) => {
    if (!modelId) return;
    setSelectedModel(modelId);
    localStorage.setItem('ace-model', modelId);
    if (!isTurboModel(modelId)) {
      setInferenceSteps(20);
      setUseAdg(true);
    }
    setShowModelMenu(false);
  }, []);

  // Live DiT switch whenever selection changes (works even if menu onClick fails on mobile)
  const ditSwitchInitRef = useRef(true);
  useEffect(() => {
    if (ditSwitchInitRef.current) {
      ditSwitchInitRef.current = false;
      return;
    }
    const modelId = selectedModel;
    if (!modelId || !modelId.startsWith('acestep-v15-')) return;
    let cancelled = false;
    (async () => {
      try {
        console.log('[DiT switch] requesting', modelId);
        const r = await fetch('/api/generate/switch-dit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: modelId }),
        });
        const d = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok || d.success === false) {
          console.error('[DiT switch]', d.error || d);
        } else {
          console.log('[DiT switch]', d.message || d.loaded_model || modelId);
        }
      } catch (err: any) {
        if (!cancelled) console.error('[DiT switch]', err);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedModel]);'''
        if turbo_fn in text:
            text = text.replace(turbo_fn, helper, 1)
            print("OK selectDitModel + useEffect switch")
        else:
            print("WARN: isTurboModel block not found for helper insert", file=sys.stderr)

    # --- Replace menu item handlers to use selectDitModel + pointer ---
    old_onclick = """                        onClick={() => {
                          setSelectedModel(model.id);
                          localStorage.setItem('ace-model', model.id);
                          // Auto-adjust parameters for non-turbo models
                          if (!isTurboModel(model.id)) {
                            setInferenceSteps(20);
                            setUseAdg(true);
                          }
                          setShowModelMenu(false);
                        }}"""
    new_onclick = """                        onPointerUp={(e) => {
                          // Mobile Safari often skips click on absolute menus; pointerup is reliable
                          e.preventDefault();
                          selectDitModel(model.id);
                        }}
                        onClick={(e) => {
                          e.preventDefault();
                          selectDitModel(model.id);
                        }}"""

    if old_onclick in text:
        text = text.replace(old_onclick, new_onclick, 1)
        print("OK model menu onPointerUp/onClick")
    elif "selectDitModel(model.id)" in text:
        print("model menu already uses selectDitModel")
    else:
        # Try already-patched async onClick from older patch
        if "/api/generate/switch-dit" in text and "setSelectedModel(model.id)" in text:
            # replace any remaining simple onClick that only sets state
            pat = re.compile(
                r"onClick=\{\(\)\s*=>\s*\{\s*setSelectedModel\(model\.id\);\s*"
                r"localStorage\.setItem\('ace-model', model\.id\);[\s\S]*?setShowModelMenu\(false\);\s*\}\}",
                re.M,
            )
            if pat.search(text):
                text = pat.sub(
                    "onPointerUp={(e) => { e.preventDefault(); selectDitModel(model.id); }}\n"
                    "                        onClick={(e) => { e.preventDefault(); selectDitModel(model.id); }}",
                    text,
                    count=1,
                )
                print("OK replaced residual onClick with selectDitModel")
            else:
                print("WARN: could not locate model menu onClick", file=sys.stderr)

    if text != original:
        p.write_text(text)
        print(f"Wrote {p}")
    else:
        print(f"No CreatePanel text changes needed (or already patched): {p}")


def patch_acestep_service() -> None:
    p = _find("acestep.ts", "services") or Path("server/src/services/acestep.ts")
    if not p.is_file():
        print("acestep.ts not found", file=sys.stderr)
        return
    text = p.read_text()

    new_get = r'''
async function getActiveModel(): Promise<string | null> {
  try {
    const res = await fetch(`${ACESTEP_API}/v1/models`);
    if (!res.ok) return null;
    const data = await res.json() as any;
    const payload = data?.data || data || {};
    if (payload.default_model) return String(payload.default_model);
    if (payload.loaded_model) return String(payload.loaded_model);
    const models = payload.models || [];
    const active = models.find(
      (m: any) => m && (m.is_loaded || m.is_active || m.is_default)
    );
    if (active?.name) return String(active.name);
    return models[0]?.name ? String(models[0].name) : null;
  } catch {
    return null;
  }
}
'''

    new_switch = r'''
async function switchModelIfNeeded(ditModel: string): Promise<void> {
  if (!ditModel || !String(ditModel).trim()) return;
  const target = String(ditModel).trim();
  const activeModel = await getActiveModel();
  const norm = (s: string | null) =>
    (s || '').split('/').pop()?.replace(/\/+$/, '') || '';
  if (norm(activeModel) === norm(target)) {
    console.log(`[Model] Already on '${target}' (active='${activeModel}')`);
    return;
  }

  console.log(`[Model] Switching from '${activeModel ?? 'unknown'}' to '${target}'`);
  const res = await fetch(`${ACESTEP_API}/v1/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: target, init_llm: false }),
    signal: AbortSignal.timeout(600_000),
  });

  if (!res.ok) {
    const err = await res.text().catch(() => '');
    throw new Error(`Model switch to '${target}' failed: ${res.status} ${err}`);
  }
  let body: any = null;
  try { body = await res.json(); } catch { /* ignore */ }
  const loaded = body?.data?.loaded_model || body?.loaded_model || target;
  console.log(`[Model] Switched to '${loaded}'`);
}
'''

    if "Prefer explicit fields from our Gradio" in text or "payload.default_model" in text:
        print("getActiveModel already hardened")
    else:
        pat = re.compile(
            r"async function getActiveModel\(\): Promise<string \| null> \{[\s\S]*?\n\}",
            re.M,
        )
        if pat.search(text):
            text = pat.sub(new_get.strip(), text, count=1)
            print("OK replaced getActiveModel")
        else:
            text = new_get + "\n" + text
            print("OK prepended getActiveModel")

    if "norm(activeModel) === norm(target)" in text:
        print("switchModelIfNeeded already hardened")
    else:
        pat = re.compile(
            r"async function switchModelIfNeeded\(ditModel: string\): Promise<void> \{[\s\S]*?\n\}",
            re.M,
        )
        if pat.search(text):
            text = pat.sub(new_switch.strip(), text, count=1)
            print("OK replaced switchModelIfNeeded")
        else:
            text = new_switch + "\n" + text
            print("OK inserted switchModelIfNeeded")

    p.write_text(text)
    print(f"Wrote {p}")


def main() -> None:
    patch_generate_ts()
    patch_create_panel()
    patch_acestep_service()
    print("createpanel-dit-live-switch patch complete")


if __name__ == "__main__":
    main()
