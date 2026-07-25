#!/usr/bin/env python3
"""Live-switch DiT when user picks a model in Create panel (incl. XL).

Problem: Generate was still running turbo even when the dropdown showed XL.
Upstream only calls switchModelIfNeeded at generate time, and getActiveModel()
used models[0] which can disagree with the real loaded DiT.

This patch:
1. Adds POST /api/generate/switch-dit -> Gradio /v1/init {model}
2. CreatePanel model-menu onClick calls switch-dit right away
3. Hardens getActiveModel + switchModelIfNeeded in acestep.ts
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
// Body: { model: "acestep-v15-xl-turbo" | "acestep-v15-turbo" | ... }
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
    if "/api/generate/switch-dit" in text:
        print("CreatePanel DiT live switch already wired")
        return

    # Typical upstream onClick for model menu items
    old = """            onClick={() => {
              setSelectedModel(model.id);
              localStorage.setItem('ace-model', model.id);
              // Auto-adjust parameters for non-turbo models
              if (!isTurboModel(model.id)) {
                setInferenceSteps(20);
                setUseAdg(true);
              }
              setShowModelMenu(false);
            }}"""

    new = """            onClick={async () => {
              setSelectedModel(model.id);
              localStorage.setItem('ace-model', model.id);
              // Auto-adjust parameters for non-turbo models
              if (!isTurboModel(model.id)) {
                setInferenceSteps(20);
                setUseAdg(true);
              } else {
                // turbo family prefers low steps / no ADG
                setInferenceSteps((s) => (s > 8 ? 8 : s));
              }
              setShowModelMenu(false);
              // Live DiT switch (same path as curl /v1/init) so Generate
              // does not stay on turbo when XL is selected.
              try {
                const r = await fetch('/api/generate/switch-dit', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ model: model.id }),
                });
                const d = await r.json();
                if (!r.ok || d.success === false) {
                  console.error('[DiT switch]', d.error || d);
                  alert('Model switch failed: ' + (d.error || r.status));
                } else {
                  console.log('[DiT switch]', d.message || d.loaded_model || model.id);
                }
              } catch (err: any) {
                console.error('[DiT switch]', err);
                alert('Model switch failed: ' + (err?.message || String(err)));
              }
            }}"""

    if old in text:
        text = text.replace(old, new, 1)
        p.write_text(text)
        print(f"OK CreatePanel DiT onClick live switch -> {p}")
        return

    # Fallback: any setSelectedModel(model.id) block inside model map onClick
    pat = re.compile(
        r"onClick=\{\(\)\s*=>\s*\{\s*setSelectedModel\(model\.id\);\s*localStorage\.setItem\('ace-model', model\.id\);",
        re.S,
    )
    m = pat.search(text)
    if not m:
        print("WARN: could not find DiT model onClick in CreatePanel", file=sys.stderr)
        return

    # Expand to async + switch-dit after localStorage line
    repl = """onClick={async () => {
              setSelectedModel(model.id);
              localStorage.setItem('ace-model', model.id);
              try {
                const r = await fetch('/api/generate/switch-dit', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ model: model.id }),
                });
                const d = await r.json();
                if (!r.ok || d.success === false) {
                  console.error('[DiT switch]', d.error || d);
                  alert('Model switch failed: ' + (d.error || r.status));
                } else {
                  console.log('[DiT switch]', d.message || d.loaded_model || model.id);
                }
              } catch (err: any) {
                console.error('[DiT switch]', err);
                alert('Model switch failed: ' + (err?.message || String(err)));
              }"""
    text = text[: m.start()] + repl + text[m.end() :]
    p.write_text(text)
    print(f"OK CreatePanel DiT onClick (fallback) -> {p}")


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
    // Prefer explicit fields from our Gradio /v1/models patch
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

    if "Prefer explicit fields from our Gradio" in text:
        print("getActiveModel already hardened")
    else:
        # Replace existing getActiveModel function body
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
            # insert after getActiveModel
            if "async function getActiveModel" in text:
                text = text.replace(
                    new_get.strip(),
                    new_get.strip() + "\n\n" + new_switch.strip(),
                    1,
                )
            else:
                text = new_switch + "\n" + text
            print("OK inserted switchModelIfNeeded")

    # Ensure generation always attempts switch when ditModel present
    if "if (params.ditModel)" in text and "await switchModelIfNeeded(params.ditModel)" in text:
        print("generation-time DiT switch call present")
    elif "processGenerationViaGradio" in text and "switchModelIfNeeded" in text:
        print("switchModelIfNeeded referenced — leave call sites")

    p.write_text(text)
    print(f"Wrote {p}")


def main() -> None:
    patch_generate_ts()
    patch_create_panel()
    patch_acestep_service()
    print("createpanel-dit-live-switch patch complete")


if __name__ == "__main__":
    main()
