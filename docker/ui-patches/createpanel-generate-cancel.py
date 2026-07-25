#!/usr/bin/env python3
"""Cancel generation from the Create/Generate button.

While isGenerating, a second click prompts:
  "Are you sure you want to stop this generation?"
Yes -> POST /api/generate/cancel-all (or per-job cancel), clear UI queue.

Backend marks generation_jobs status=failed with error='cancelled by user'
and best-effort marks in-memory ActiveJob failed. Gradio work already on
the XPU may still complete on disk; the UI queue clears immediately.
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


def patch_generate_routes() -> None:
    p = _find("generate.ts", "routes") or Path("server/src/routes/generate.ts")
    if not p.is_file():
        print("generate.ts not found", file=sys.stderr)
        sys.exit(1)
    text = p.read_text()
    if "/cancel-all" in text and "cancelled by user" in text:
        print("cancel routes already present")
        return

    block = r'''
// POST /api/generate/cancel/:jobId — mark one job cancelled
router.post('/cancel/:jobId', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const jobId = String(req.params.jobId || '').trim();
    if (!jobId) {
      res.status(400).json({ error: 'jobId required' });
      return;
    }
    const userId = req.user!.id;
    const result = await pool.query(
      `UPDATE generation_jobs
       SET status = 'failed',
           error = 'cancelled by user',
           updated_at = datetime('now')
       WHERE id = ? AND user_id = ? AND status IN ('pending','queued','running')`,
      [jobId, userId]
    );
    // best-effort in-memory cancel if service exports it
    try {
      const mod = await import('../services/acestep.js');
      if (typeof (mod as any).cancelJob === 'function') {
        await (mod as any).cancelJob(jobId);
      }
    } catch { /* optional */ }
    const changes = (result as any)?.changes ?? (result as any)?.rowCount ?? 1;
    res.json({ success: true, jobId, cancelled: true, changes });
  } catch (e: any) {
    console.error('[cancel]', e);
    res.status(500).json({ error: e?.message || 'cancel failed' });
  }
});

// POST /api/generate/cancel-all — cancel all active jobs for this user
router.post('/cancel-all', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const userId = req.user!.id;
    const listed = await pool.query(
      `SELECT id FROM generation_jobs
       WHERE user_id = ? AND status IN ('pending','queued','running')`,
      [userId]
    );
    const rows = (listed as any).rows || listed || [];
    const ids: string[] = Array.isArray(rows)
      ? rows.map((r: any) => r.id || r[0]).filter(Boolean)
      : [];
    await pool.query(
      `UPDATE generation_jobs
       SET status = 'failed',
           error = 'cancelled by user',
           updated_at = datetime('now')
       WHERE user_id = ? AND status IN ('pending','queued','running')`,
      [userId]
    );
    try {
      const mod = await import('../services/acestep.js');
      if (typeof (mod as any).cancelJob === 'function') {
        for (const id of ids) {
          try { await (mod as any).cancelJob(id); } catch { /* ignore */ }
        }
      }
    } catch { /* optional */ }
    res.json({ success: true, cancelled: ids, count: ids.length });
  } catch (e: any) {
    console.error('[cancel-all]', e);
    res.status(500).json({ error: e?.message || 'cancel-all failed' });
  }
});
'''

    if "router.post('/switch-dit'" in text:
        text = text.replace(
            "router.post('/switch-dit'",
            block.strip() + "\n\nrouter.post('/switch-dit'",
            1,
        )
    elif "router.post('/switch-lm'" in text:
        text = text.replace(
            "router.post('/switch-lm'",
            block.strip() + "\n\nrouter.post('/switch-lm'",
            1,
        )
    elif "export default router" in text:
        text = text.replace(
            "export default router",
            block.strip() + "\n\nexport default router",
            1,
        )
    else:
        text = text.rstrip() + "\n" + block + "\n"

    p.write_text(text)
    print(f"OK cancel routes in {p}")


def patch_acestep_cancel() -> None:
    p = _find("acestep.ts", "services") or Path("server/src/services/acestep.ts")
    if not p.is_file():
        print("acestep.ts not found — skip cancelJob export")
        return
    text = p.read_text()
    if "export async function cancelJob" in text or "export function cancelJob" in text:
        print("cancelJob already exported")
        return

    helper = r'''
/** Mark an in-memory ActiveJob as failed/cancelled so queue processors stop. */
export async function cancelJob(jobId: string): Promise<boolean> {
  try {
    // activeJobs is the in-memory map used by this module (name varies by version)
    const map: Map<string, any> |
      undefined =
      (globalThis as any).__aceActiveJobs ||
      (typeof activeJobs !== 'undefined' ? (activeJobs as any) : undefined);
    if (map && map.has(jobId)) {
      const job = map.get(jobId);
      if (job) {
        job.status = 'failed';
        job.error = 'cancelled by user';
        job.stage = 'cancelled';
      }
      return true;
    }
  } catch (e) {
    console.warn('[cancelJob]', e);
  }
  return false;
}
'''
    # Try to capture activeJobs Map reference into global for cancelJob
    if "const activeJobs" in text or "let activeJobs" in text:
        text = re.sub(
            r"((?:const|let)\s+activeJobs\s*=\s*new\s+Map[^;]*;)",
            r"\1\n(globalThis as any).__aceActiveJobs = activeJobs;",
            text,
            count=1,
        )
    text = text.rstrip() + "\n" + helper + "\n"
    p.write_text(text)
    print(f"OK cancelJob export in {p}")


def patch_create_panel() -> None:
    p = _find("CreatePanel.tsx") or Path("components/CreatePanel.tsx")
    if not p.is_file():
        print("CreatePanel.tsx not found", file=sys.stderr)
        sys.exit(1)
    text = p.read_text()
    if "stop this generation" in text or "onCancelActiveGenerations" in text:
        print("CreatePanel cancel already wired")
        return

    # Add optional prop to interface if present
    if "isGenerating: boolean" in text and "onCancelActiveGenerations" not in text:
        text = text.replace(
            "isGenerating: boolean",
            "isGenerating: boolean;\n  onCancelActiveGenerations?: () => void | Promise<void>",
            1,
        )

    # Destructure prop
    if re.search(r"isGenerating[,\s}]", text) and "onCancelActiveGenerations" not in text.split("CreatePanel")[1][:800] if "CreatePanel" in text else True:
        text = re.sub(
            r"(isGenerating)([,\s}])",
            r"\1, onCancelActiveGenerations\2",
            text,
            count=1,
        )

    # Replace disabled Generate/Create footer button behavior
    # Pattern 1: disabled={isGenerating || !isAuthenticated}
    text2 = text.replace(
        "disabled={isGenerating || !isAuthenticated}",
        "disabled={!isAuthenticated}",
    )
    # Pattern 2: disabled={isGenerating}
    text2 = re.sub(
        r"disabled=\{isGenerating\}",
        "disabled={false}",
        text2,
        count=2,
    )

    # Replace onClick={handleGenerate} on the main create button with dual handler
    # Prefer the sticky footer create button context
    dual = """onClick={async () => {
      if (isGenerating) {
        const ok = window.confirm('Are you sure you want to stop this generation?');
        if (!ok) return;
        try {
          if (onCancelActiveGenerations) {
            await onCancelActiveGenerations();
          } else {
            await fetch('/api/generate/cancel-all', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
          }
        } catch (e) {
          console.error('Cancel failed', e);
          alert('Cancel failed: ' + (e as any)?.message || e);
        }
        return;
      }
      handleGenerate();
    }}"""

    # Only replace the primary create button onClick if we can find handleGenerate onClick
    if "onClick={handleGenerate}" in text2:
        # Replace all handleGenerate onClick on buttons that also show generating text — typically 1-2
        text2 = text2.replace("onClick={handleGenerate}", dual, 1)
        if "onClick={handleGenerate}" in text2:
            # second occurrence (advanced section generate)
            text2 = text2.replace("onClick={handleGenerate}", dual, 1)
    else:
        print("WARN: onClick={handleGenerate} not found", file=sys.stderr)

    # Visual: when generating, show Cancel-ish label
    text2 = text2.replace(
        "{isGenerating \n        ? t('generating')",
        "{isGenerating \n        ? (t('generating') + ' — tap to cancel')",
        1,
    )
    # simpler single-line variants
    text2 = text2.replace(
        "{isGenerating ? (\n        <>\n        <Loader2",
        "{isGenerating ? (\n        <>\n        <Loader2",
        1,
    )
    if "t('generating')" in text2 and "tap to cancel" not in text2:
        text2 = text2.replace(
            "{isGenerating ? t('generating') :",
            "{isGenerating ? (t('generating') + ' — tap to cancel') :",
            1,
        )

    p.write_text(text2)
    print(f"OK CreatePanel cancel click -> {p}")


def patch_app() -> None:
    p = _find("App.tsx") or Path("App.tsx")
    if not p.is_file():
        print("App.tsx not found", file=sys.stderr)
        return
    text = p.read_text()
    if "onCancelActiveGenerations" in text and "cancel-all" in text:
        print("App cancel handler already present")
        return

    handler = r'''
  const onCancelActiveGenerations = useCallback(async () => {
    const entries = Array.from(activeJobsRef.current.entries());
    try {
      await fetch('/api/generate/cancel-all', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch (e) {
      console.error('cancel-all request failed', e);
    }
    for (const [jobId, { tempId }] of entries) {
      try {
        await fetch(`/api/generate/cancel/${jobId}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
      } catch { /* ignore */ }
      cleanupJob(jobId, tempId);
    }
    setIsGenerating(false);
    showToast?.('Generation cancelled', 'info');
  }, [token, cleanupJob]);
'''

    # Insert before CreatePanel usage or after cleanupJob
    if "const cleanupJob = useCallback" in text:
        # after cleanupJob block is hard; insert before CreatePanel JSX
        pass
    if "<CreatePanel" in text and "onCancelActiveGenerations" not in text:
        # define handler just before return if possible — inject after activeJobsRef
        if "const [isGenerating, setIsGenerating]" in text:
            text = text.replace(
                "const [isGenerating, setIsGenerating] = useState(false);",
                "const [isGenerating, setIsGenerating] = useState(false);\n"
                + "  // cancel handler placed later after cleanupJob",
                1,
            )
        # Place handler after cleanupJob definition ends — find setIsGenerating(false) inside cleanupJob close
        m = re.search(
            r"(const cleanupJob = useCallback\([\s\S]*?\}, \[\]\);)",
            text,
        )
        if m:
            text = text[: m.end()] + "\n" + handler + text[m.end() :]
        else:
            # fallback: before CreatePanel
            text = text.replace(
                "<CreatePanel",
                handler + "\n      <CreatePanel",
                1,
            )

        text = text.replace(
            "<CreatePanel\n  onGenerate={handleGenerate}\n  isGenerating={isGenerating}",
            "<CreatePanel\n  onGenerate={handleGenerate}\n  onCancelActiveGenerations={onCancelActiveGenerations}\n  isGenerating={isGenerating}",
            1,
        )
        # alternate formatting
        text = text.replace(
            "onGenerate={handleGenerate}\n  isGenerating={isGenerating}",
            "onGenerate={handleGenerate}\n  onCancelActiveGenerations={onCancelActiveGenerations}\n  isGenerating={isGenerating}",
            1,
        )
        if "onCancelActiveGenerations={onCancelActiveGenerations}" not in text:
            text = text.replace(
                "onGenerate={handleGenerate}",
                "onGenerate={handleGenerate}\n  onCancelActiveGenerations={onCancelActiveGenerations}",
                1,
            )

    p.write_text(text)
    print(f"OK App.tsx cancel handler -> {p}")


def main() -> None:
    patch_generate_routes()
    patch_acestep_cancel()
    patch_create_panel()
    patch_app()
    print("createpanel-generate-cancel patch complete")


if __name__ == "__main__":
    main()
