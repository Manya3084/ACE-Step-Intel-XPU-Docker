#!/usr/bin/env python3
"""Wire Create-panel LM Model dropdown to live Gradio /v1/init.

Upstream only stores lmModel in localStorage; generation never re-inits
the 5Hz LM. This patch:

1. Adds POST /api/generate/switch-lm on the Express side that proxies to
   Gradio POST /v1/init with {init_llm: true, lm_model_path}.
2. Makes the Advanced Settings LM Model <select> call that endpoint on
   change (0.6B / 1.7B / 4B).
3. Extends acestep.ts so processGeneration also switches LM if the
   requested lmModel differs from the currently loaded one.
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
    if "/switch-lm" in text and "lm_model_path" in text:
        print("switch-lm endpoint already present in generate.ts")
        return

    endpoint = r'''
// POST /api/generate/switch-lm — live-switch 5Hz LM via Gradio /v1/init
// Body: { lm_model_path: "acestep-5Hz-lm-0.6B" | "acestep-5Hz-lm-1.7B" | "acestep-5Hz-lm-4B" }
router.post('/switch-lm', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    let lm = String(
      body.lm_model_path || body.lmModel || body.lm_model || body.model || ''
    ).trim();
    if (!lm) {
      res.status(400).json({ error: 'lm_model_path is required' });
      return;
    }
    // Normalize bare sizes: "4B" / "1.7B" / "0.6B"
    if (!lm.startsWith('acestep-5Hz-lm-')) {
      if (/^[0-9.]+B$/i.test(lm)) {
        lm = `acestep-5Hz-lm-${lm}`;
      }
    }
    const allowed = new Set([
      'acestep-5Hz-lm-0.6B',
      'acestep-5Hz-lm-1.7B',
      'acestep-5Hz-lm-4B',
    ]);
    if (!allowed.has(lm) && !lm.startsWith('acestep-5Hz-lm-')) {
      res.status(400).json({ error: `Unsupported LM model: ${lm}` });
      return;
    }

    const ACESTEP_API_URL = config.acestep.apiUrl;
    console.log(`[switch-lm] POST ${ACESTEP_API_URL}/v1/init init_llm lm_model_path=${lm}`);
    const apiRes = await fetch(`${ACESTEP_API_URL}/v1/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_llm: true, lm_model_path: lm }),
      signal: AbortSignal.timeout(600_000), // 4B load can take minutes on CPU offload
    });
    const apiData = await apiRes.json() as any;
    if (!apiRes.ok || (apiData.code != null && apiData.code !== 200)) {
      const errMsg = apiData.error || apiData.detail || `switch-lm returned ${apiRes.status}`;
      console.error('[switch-lm] failed:', errMsg);
      res.status(500).json({ success: false, error: errMsg });
      return;
    }
    const data = apiData.data || apiData;
    res.json({
      success: true,
      loaded_lm_model: data.loaded_lm_model || lm,
      lm_switched: data.lm_switched ?? true,
      lm_offload_to_cpu: data.lm_offload_to_cpu,
      lm_device: data.lm_device,
      checkpoint_dir: data.checkpoint_dir,
      message: data.lm_message || data.message || `LM ${lm} ready`,
      lm_models: data.lm_models,
    });
  } catch (error: any) {
    console.error('[switch-lm] error:', error);
    res.status(500).json({ success: false, error: error?.message || String(error) });
  }
});
'''

    # Insert before the first router.get('/models' or at end before export
    anchor = "router.get('/models'"
    if anchor in text:
        text = text.replace(anchor, endpoint.strip() + "\n\n" + anchor, 1)
    else:
        # append before export default
        if "export default router" in text:
            text = text.replace(
                "export default router",
                endpoint.strip() + "\n\nexport default router",
                1,
            )
        else:
            text = text.rstrip() + "\n" + endpoint + "\n"

    p.write_text(text)
    print(f"OK added POST /switch-lm to {p}")


def patch_create_panel() -> None:
    p = _find("CreatePanel.tsx") or Path("components/CreatePanel.tsx")
    if not p.is_file():
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    text = p.read_text()
    if "/api/generate/switch-lm" in text:
        print("CreatePanel LM switch already wired")
        return

    # Match the simple localStorage-only onChange used upstream
    patterns = [
        (
            r"onChange=\{\(e\)\s*=>\s*\{\s*const v = e\.target\.value;\s*setLmModel\(v\);\s*localStorage\.setItem\('ace-lmModel', v\);\s*\}\}",
            '''onChange={async (e) => {
                  const v = e.target.value;
                  setLmModel(v);
                  localStorage.setItem('ace-lmModel', v);
                  try {
                    const r = await fetch('/api/generate/switch-lm', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ lm_model_path: v }),
                    });
                    const d = await r.json();
                    if (!r.ok || d.success === false) {
                      console.error('[LM switch]', d.error || d);
                      alert('LM switch failed: ' + (d.error || r.status));
                    } else {
                      console.log('[LM switch]', d.message || d.loaded_lm_model || v);
                    }
                  } catch (err: any) {
                    console.error('[LM switch]', err);
                    alert('LM switch failed: ' + (err?.message || String(err)));
                  }
                }}''',
        ),
        # Alternate: selectedLm / setSelectedLm style
        (
            r"onChange=\{\(e\)\s*=>\s*\{\s*const newModel = e\.target\.value;\s*setSelectedLm\(newModel\);[\s\S]*?\}\}",
            '''onChange={async (e) => {
                  const newModel = e.target.value;
                  setSelectedLm(newModel);
                  localStorage.setItem('ace-lmModel', newModel);
                  try {
                    const r = await fetch('/api/generate/switch-lm', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ lm_model_path: newModel }),
                    });
                    const d = await r.json();
                    if (!r.ok || d.success === false) {
                      console.error('[LM switch]', d.error || d);
                      alert('LM switch failed: ' + (d.error || r.status));
                    } else {
                      console.log('[LM switch]', d.message || d.loaded_lm_model || newModel);
                    }
                  } catch (err: any) {
                    console.error('[LM switch]', err);
                    alert('LM switch failed: ' + (err?.message || String(err)));
                  }
                }}''',
        ),
    ]

    applied = False
    for pat, repl in patterns:
        if re.search(pat, text):
            text = re.sub(pat, repl, text, count=1)
            applied = True
            print(f"OK CreatePanel LM onChange wired ({pat[:40]}...)")
            break

    if not applied:
        # Last-resort: find the <select value={lmModel} block and inject
        m = re.search(
            r"(<select\s+[^>]*value=\{lmModel\}[^>]*)(onChange=\{[^}]+\})",
            text,
        )
        if m:
            text = text[: m.start(2)] + patterns[0][1] + text[m.end(2) :]
            applied = True
            print("OK CreatePanel LM onChange wired (select value={lmModel})")

    if not applied:
        print("WARN: could not find LM Model onChange in CreatePanel.tsx", file=sys.stderr)
        # Don't fail the build — endpoint still helps generation path
    else:
        p.write_text(text)
        print(f"Wrote {p}")


def patch_acestep_service() -> None:
    """Also switch LM at generation time if params.lmModel differs."""
    p = _find("acestep.ts", "services") or Path("server/src/services/acestep.ts")
    if not p.is_file():
        print("acestep.ts not found — skip generation-time LM switch")
        return
    text = p.read_text()
    if "switchLmIfNeeded" in text:
        print("switchLmIfNeeded already present")
        return

    helper = r'''
async function switchLmIfNeeded(lmModel?: string): Promise<void> {
  if (!lmModel || !String(lmModel).trim()) return;
  let target = String(lmModel).trim();
  if (!target.startsWith('acestep-5Hz-lm-') && /^[0-9.]+B$/i.test(target)) {
    target = `acestep-5Hz-lm-${target}`;
  }
  try {
    // Ask Gradio what is loaded
    let loaded: string | null = null;
    try {
      const res = await fetch(`${config.acestep.apiUrl}/v1/models`);
      if (res.ok) {
        const data = await res.json() as any;
        loaded = data?.data?.loaded_lm_model || data?.loaded_lm_model || null;
      }
    } catch { /* ignore */ }
    if (loaded && loaded === target) {
      console.log(`[switchLmIfNeeded] already on ${target}`);
      return;
    }
    console.log(`[switchLmIfNeeded] ${loaded || '?'} -> ${target}`);
    const apiRes = await fetch(`${config.acestep.apiUrl}/v1/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_llm: true, lm_model_path: target }),
      signal: AbortSignal.timeout(600_000),
    });
    const apiData = await apiRes.json() as any;
    if (!apiRes.ok || (apiData.code != null && apiData.code !== 200)) {
      const err = apiData.error || apiData.detail || apiRes.status;
      console.warn('[switchLmIfNeeded] failed:', err);
      return; // non-fatal — generation can still proceed with currently loaded LM
    }
    console.log('[switchLmIfNeeded] ok:', apiData?.data?.loaded_lm_model || target);
  } catch (e: any) {
    console.warn('[switchLmIfNeeded] error:', e?.message || e);
  }
}
'''

    # Insert helper near switchModelIfNeeded if present
    if "async function switchModelIfNeeded" in text:
        text = text.replace(
            "async function switchModelIfNeeded",
            helper.strip() + "\n\nasync function switchModelIfNeeded",
            1,
        )
    else:
        # place after imports / before first export async
        m = re.search(r"\nexport async function", text)
        if m:
            text = text[: m.start()] + "\n" + helper + text[m.start() :]
        else:
            text = text + "\n" + helper

    # Call it from processGenerationViaGradio (or similar) after DiT switch
    call_site_patterns = [
        (r"(await switchModelIfNeeded\([^)]*\);)", r"\1\n  await switchLmIfNeeded(params.lmModel);"),
        (r"(await switchModelIfNeeded\([^)]*\))",
         r"\1;\n  await switchLmIfNeeded(params.lmModel)"),
    ]
    called = False
    for pat, repl in call_site_patterns:
        if re.search(pat, text) and "switchLmIfNeeded(params.lmModel)" not in text:
            text = re.sub(pat, repl, text, count=1)
            called = True
            break

    if not called and "switchLmIfNeeded(params.lmModel)" not in text:
        # Try to inject near processGenerationViaGradio start
        m = re.search(r"(async function processGenerationViaGradio[^{]*\{)", text)
        if m:
            text = (
                text[: m.end()]
                + "\n  await switchLmIfNeeded(params.lmModel);"
                + text[m.end() :]
            )
            called = True

    p.write_text(text)
    print(f"OK switchLmIfNeeded in {p} (call_site={called})")


def main() -> None:
    patch_generate_ts()
    patch_create_panel()
    patch_acestep_service()
    print("createpanel-lm-switch patch complete")


if __name__ == "__main__":
    main()
