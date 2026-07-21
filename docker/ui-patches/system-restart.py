#!/usr/bin/env python3
"""Applied inside Dockerfile.ui build — restart API + floating UI button."""
from pathlib import Path
import re

# --- API route ---
lines = [
    "import { Router, Response } from 'express';",
    "import { execFile } from 'child_process';",
    "import { promisify } from 'util';",
    "import { authMiddleware, AuthenticatedRequest } from '../middleware/auth.js';",
    "",
    "const execFileAsync = promisify(execFile);",
    "const router = Router();",
    "",
    "function restartEnabled(): boolean {",
    "  return (process.env.ENABLE_DOCKER_RESTART || 'true').toLowerCase() !== 'false';",
    "}",
    "",
    "function containerName(): string {",
    "  return process.env.XPU_CONTAINER_NAME || 'acestep-xpu';",
    "}",
    "",
    "router.get('/restart-xpu/status', authMiddleware, async (_req: AuthenticatedRequest, res: Response) => {",
    "  const enabled = restartEnabled();",
    "  const name = containerName();",
    "  if (!enabled) {",
    "    res.json({ enabled: false, container: name, reason: 'ENABLE_DOCKER_RESTART=false' });",
    "    return;",
    "  }",
    "  try {",
    "    const { stdout } = await execFileAsync('docker', ['inspect', '-f', '{{.State.Status}}', name], { timeout: 10000 });",
    "    res.json({ enabled: true, container: name, status: stdout.trim() });",
    "  } catch (err: any) {",
    "    res.json({ enabled: true, container: name, status: 'unknown', error: String(err?.message || err) });",
    "  }",
    "});",
    "",
    "router.post('/restart-xpu', authMiddleware, async (_req: AuthenticatedRequest, res: Response) => {",
    "  if (!restartEnabled()) {",
    "    res.status(403).json({ error: 'Docker restart disabled (ENABLE_DOCKER_RESTART=false)' });",
    "    return;",
    "  }",
    "  const name = containerName();",
    "  try {",
    "    console.log('[system] Restarting container', name);",
    "    await execFileAsync('docker', ['restart', name], { timeout: 120000 });",
    "    res.json({",
    "      ok: true,",
    "      container: name,",
    "      message: 'Restart issued. Wait 1–3 minutes for models to reload before generating.',",
    "    });",
    "  } catch (err: any) {",
    "    console.error('[system] restart failed', err);",
    "    res.status(500).json({",
    "      error: 'Failed to restart container. Is /var/run/docker.sock mounted and docker CLI available?',",
    "      detail: String(err?.stderr || err?.message || err),",
    "    });",
    "  }",
    "});",
    "",
    "export default router;",
    "",
]
Path("server/src/routes/system.ts").write_text("\n".join(lines))
print("Wrote server/src/routes/system.ts")

# --- register in index.ts ---
idx = Path("server/src/index.ts")
it = idx.read_text()
if "/api/system" not in it:
    if "import settingsRoutes" in it:
        it = it.replace(
            "import settingsRoutes from './routes/settings.js';",
            "import settingsRoutes from './routes/settings.js';\nimport systemRoutes from './routes/system.js';",
        )
    elif "import trainingRoutes" in it:
        it = it.replace(
            "import trainingRoutes from './routes/training.js';",
            "import trainingRoutes from './routes/training.js';\nimport systemRoutes from './routes/system.js';",
        )
    else:
        it = "import systemRoutes from './routes/system.js';\n" + it

    if "app.use('/api/settings'" in it:
        it = it.replace(
            "app.use('/api/settings', settingsRoutes);",
            "app.use('/api/settings', settingsRoutes);\napp.use('/api/system', systemRoutes);",
        )
    elif "app.use('/api/auth'" in it:
        it = it.replace(
            "app.use('/api/auth', authRoutes);",
            "app.use('/api/auth', authRoutes);\napp.use('/api/system', systemRoutes);",
        )
    idx.write_text(it)
    print("Registered /api/system")
else:
    print("/api/system already registered")

# --- floating restart control (public/js injected via index.html) ---
btn_js = r'''
(function () {
  function token() {
    try {
      for (const k of ['token', 'authToken', 'access_token', 'ace-step-token', 'jwt']) {
        const v = localStorage.getItem(k);
        if (v && v.length > 20) return v.replace(/^Bearer\s+/i, '');
      }
      for (const k of ['auth', 'user', 'ace-step-auth']) {
        const raw = localStorage.getItem(k);
        if (!raw) continue;
        try {
          const o = JSON.parse(raw);
          if (o && o.token) return String(o.token);
        } catch (e) {}
      }
    } catch (e) {}
    return null;
  }

  function ensureBtn() {
    if (document.getElementById('ace-xpu-restart-btn')) return;
    const wrap = document.createElement('div');
    wrap.id = 'ace-xpu-restart-wrap';
    wrap.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:99999;display:flex;flex-direction:column;align-items:flex-end;gap:6px;font-family:system-ui,sans-serif;';
    const btn = document.createElement('button');
    btn.id = 'ace-xpu-restart-btn';
    btn.type = 'button';
    btn.textContent = 'Restart acestep-xpu';
    btn.style.cssText = 'background:#1db954;color:#000;border:none;border-radius:999px;padding:10px 16px;font-weight:700;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.35);';
    const status = document.createElement('div');
    status.id = 'ace-xpu-restart-status';
    status.style.cssText = 'max-width:260px;font-size:12px;color:#ddd;background:rgba(0,0,0,.75);padding:6px 10px;border-radius:8px;display:none;';
    btn.onclick = async function () {
      const t = token();
      if (!t) {
        status.style.display = 'block';
        status.textContent = 'Log in first, then try again.';
        return;
      }
      if (!confirm('Restart acestep-xpu? Generation will be unavailable for 1–3 minutes while models reload.')) return;
      btn.disabled = true;
      btn.textContent = 'Restarting…';
      status.style.display = 'block';
      status.textContent = 'Sending restart…';
      try {
        const res = await fetch('/api/system/restart-xpu', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
        });
        const data = await res.json().catch(function () { return {}; });
        if (!res.ok) throw new Error(data.error || data.detail || ('HTTP ' + res.status));
        status.textContent = data.message || 'Restart issued. Wait for models to load.';
      } catch (e) {
        status.textContent = String(e.message || e);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Restart acestep-xpu';
      }
    };
    wrap.appendChild(status);
    wrap.appendChild(btn);
    document.body.appendChild(wrap);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(ensureBtn, 1500); });
  } else {
    setTimeout(ensureBtn, 1500);
  }
})();
'''
Path("public").mkdir(parents=True, exist_ok=True)
Path("public/ace-xpu-restart.js").write_text(btn_js)
print("Wrote public/ace-xpu-restart.js")

# Inject script into index.html if present
for html_path in ["index.html", "public/index.html"]:
    p = Path(html_path)
    if not p.exists():
        continue
    h = p.read_text()
    if "ace-xpu-restart.js" in h:
        print(f"{html_path} already has restart script")
        break
    if "</body>" in h:
        h = h.replace("</body>", '  <script src="/ace-xpu-restart.js"></script>\n</body>', 1)
    else:
        h += '\n<script src="/ace-xpu-restart.js"></script>\n'
    p.write_text(h)
    print(f"Injected restart script into {html_path}")
    break

print("system restart patch OK")
