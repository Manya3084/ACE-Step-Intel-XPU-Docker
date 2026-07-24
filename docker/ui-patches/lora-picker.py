#!/usr/bin/env python3
"""LoRA picker — open API + always visible left-sidebar block."""
from pathlib import Path
import re

lora_ts = Path("server/src/routes/lora.ts")
text = lora_ts.read_text()

text2, n_auth = re.subn(
    r"(router\.(get|post|put|delete|patch)\(\s*['\"][^'\"]+['\"]\s*),\s*authMiddleware\s*,",
    r"\1,",
    text,
)
text = text2
print(f"Removed authMiddleware from {n_auth} lora route(s)")

if "from 'fs'" not in text and 'from "fs"' not in text:
    text = (
        "import { existsSync, readdirSync, statSync } from 'fs';\n"
        "import path from 'path';\n"
        + text
    )

if "router.get('/list'" not in text and 'router.get("/list"' not in text:
    LIST = r'''
function loraRoots(): string[] {
  const roots = [
    process.env.LORA_OUTPUT_DIR || '/app/lora_output',
    '/app/lora_output',
  ];
  return [...new Set(roots.filter(Boolean))];
}

function isAdapterDir(dir: string): boolean {
  try {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) return false;
    const names = readdirSync(dir);
    return names.some(
      (n) =>
        n === 'adapter_model.safetensors' ||
        n === 'adapter_model.bin' ||
        n === 'adapter_config.json'
    );
  } catch {
    return false;
  }
}

function walkAdapters(root: string, depth = 0, out: { path: string; label: string; loss?: number; epoch?: number }[] = []) {
  if (depth > 6) return out;
  try {
    if (!existsSync(root)) return out;
    const adapterChild = path.join(root, 'adapter');
    if (isAdapterDir(adapterChild)) {
      const base = path.basename(root);
      const mLoss = base.match(/loss_([0-9.]+)/);
      const mEp = base.match(/epoch_(\d+)/);
      out.push({
        path: adapterChild,
        label: base === 'final' ? 'final' : base,
        loss: mLoss ? parseFloat(mLoss[1]) : undefined,
        epoch: mEp ? parseInt(mEp[1], 10) : undefined,
      });
      return out;
    }
    if (isAdapterDir(root)) {
      out.push({ path: root, label: path.basename(root) });
      return out;
    }
    for (const name of readdirSync(root)) {
      if (name.startsWith('.')) continue;
      const p = path.join(root, name);
      try {
        if (statSync(p).isDirectory()) walkAdapters(p, depth + 1, out);
      } catch {}
    }
  } catch {}
  return out;
}

router.get('/list', async (_req: any, res: Response) => {
  try {
    const found: { path: string; label: string; loss?: number; epoch?: number }[] = [];
    const seen = new Set<string>();
    for (const root of loraRoots()) {
      for (const a of walkAdapters(root)) {
        if (seen.has(a.path)) continue;
        seen.add(a.path);
        found.push(a);
      }
    }
    found.sort((a, b) => {
      if (a.label === 'final') return -1;
      if (b.label === 'final') return 1;
      return (b.epoch ?? -1) - (a.epoch ?? -1);
    });
    res.json({ adapters: found, current: loraState, roots: loraRoots() });
  } catch (error) {
    console.error('[LoRA] List error:', error);
    res.status(500).json({ error: error instanceof Error ? error.message : 'Failed to list LoRAs' });
  }
});
'''
    text = text.replace("export default router;", LIST + "\nexport default router;\n")
    print("Added GET /api/lora/list")
else:
    text = re.sub(
        r"router\.get\(\s*['\"]/list['\"]\s*,\s*authMiddleware\s*,",
        "router.get('/list',",
        text,
    )

if "unload before load" not in text:
    old_load = """    const client = await getGradioClient();
    const result = await client.predict('/load_lora', [lora_path]);
    const status = (result.data as unknown[])[0] as string;

    loraState = { loaded: true, active: true, scale: loraState.scale, path: lora_path };

    res.json({ message: status, lora_path, loaded: true });"""
    new_load = """    const client = await getGradioClient();
    if (loraState.loaded && loraState.path && loraState.path !== lora_path) {
      try { await client.predict('/unload_lora', []); } catch (e) { console.warn('[LoRA] pre-unload', e); }
    }
    const result = await client.predict('/load_lora', [lora_path]);
    const status = (result.data as unknown[])[0] as string;
    try { await client.predict('/set_use_lora', [true]); } catch (e) {}
    loraState = { loaded: true, active: true, scale: loraState.scale, path: lora_path };
    res.json({ message: status, lora_path, loaded: true, active: true });"""
    if old_load in text:
        text = text.replace(old_load, new_load)

lora_ts.write_text(text)
print("lora.ts updated")

# Always mount on left sidebar (not dependent on finding "LoRA" label)
js = r'''(function () {
  var HOST_ID = "ace-xpu-lora-inline";

  async function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    var r = await fetch(path, opts);
    var j = null;
    try { j = await r.json(); } catch (e) { j = { error: await r.text() }; }
    if (!r.ok) throw new Error((j && (j.error || j.detail || j.message)) || r.statusText);
    return j;
  }

  function findSidebar() {
    return (
      document.querySelector("aside") ||
      document.querySelector('[class*="sidebar" i]') ||
      document.querySelector('[class*="SideBar" i]') ||
      document.querySelector('[class*="left" i][class*="panel" i]') ||
      document.querySelector("nav") ||
      null
    );
  }

  function removeFloating() {
    var old = document.getElementById("ace-xpu-lora-panel");
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

  function buildHost() {
    var host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("data-ace-xpu", "lora-inline");
    host.style.cssText =
      "margin:12px 8px 16px;padding:12px;border:1px solid rgba(255,255,255,0.12);" +
      "border-radius:10px;background:rgba(0,0,0,0.25);";
    host.innerHTML =
      '<div style="font-size:13px;font-weight:700;margin-bottom:8px">Trained LoRA adapters</div>' +
      '<select id="ace-lora-select" style="width:100%;box-sizing:border-box;margin-bottom:8px;' +
      "background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:8px;padding:8px;font:inherit"></select>' +
      '<div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap">' +
      '<button type="button" id="ace-lora-refresh" style="padding:6px 10px;border-radius:8px;' +
      "border:1px solid #444;background:#222;color:#eee;cursor:pointer">Refresh</button>' +
      '<button type="button" id="ace-lora-load" style="flex:1;padding:6px 10px;border-radius:8px;border:0;' +
      'background:#1db954;color:#000;font-weight:700;cursor:pointer">Load</button>' +
      '<button type="button" id="ace-lora-unload" style="flex:1;padding:6px 10px;border-radius:8px;' +
      "border:1px solid #444;background:#222;color:#eee;cursor:pointer">Unload</button>' +
      "</div>" +
      '<div id="ace-lora-status" style="font-size:11px;opacity:0.8;word-break:break-all;line-height:1.35">' +
      "Loading list…</div>";
    return host;
  }

  function wire(host) {
    var sel = host.querySelector("#ace-lora-select");
    var status = host.querySelector("#ace-lora-status");

    async function refresh() {
      status.textContent = "Listing…";
      try {
        var data = await api("/api/lora/list");
        sel.innerHTML = "";
        var adapters = data.adapters || [];
        if (!adapters.length) {
          sel.innerHTML = '<option value="">(no adapters under /app/lora_output)</option>';
          status.textContent = "No adapters yet";
          return;
        }
        adapters.forEach(function (a) {
          var o = document.createElement("option");
          o.value = a.path;
          var bits = [a.label];
          if (a.epoch != null) bits.push("ep" + a.epoch);
          if (a.loss != null) bits.push("loss " + a.loss);
          o.textContent = bits.join(" · ");
          sel.appendChild(o);
        });
        if (data.current && data.current.path) {
          try { sel.value = data.current.path; } catch (e) {}
          status.textContent =
            (data.current.loaded ? "Loaded: " : "") + data.current.path;
        } else {
          status.textContent = adapters.length + " adapter(s)";
        }
      } catch (e) {
        status.textContent = String(e.message || e);
      }
    }

    host.querySelector("#ace-lora-refresh").onclick = refresh;
    host.querySelector("#ace-lora-load").onclick = async function () {
      var p = sel.value;
      if (!p) return alert("Pick an adapter");
      status.textContent = "Loading…";
      try {
        var r = await api("/api/lora/load", {
          method: "POST",
          body: JSON.stringify({ lora_path: p }),
        });
        status.textContent = "Loaded: " + p + (r.message ? " — " + r.message : "");
      } catch (e) {
        status.textContent = "Load failed: " + (e.message || e);
      }
    };
    host.querySelector("#ace-lora-unload").onclick = async function () {
      status.textContent = "Unloading…";
      try {
        var r = await api("/api/lora/unload", { method: "POST", body: "{}" });
        status.textContent = "Unloaded" + (r.message ? " — " + r.message : "");
      } catch (e) {
        status.textContent = "Unload failed: " + (e.message || e);
      }
    };
    setTimeout(refresh, 300);
  }

  function tryMount() {
    removeFloating();
    if (document.getElementById(HOST_ID)) return true;
    var side = findSidebar();
    if (!side) return false;
    var host = buildHost();
    side.appendChild(host);
    wire(host);
    return true;
  }

  function boot() {
    if (tryMount()) return;
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (tryMount() || tries > 60) clearInterval(iv);
    }, 500);
    try {
      new MutationObserver(function () {
        removeFloating();
        if (!document.getElementById(HOST_ID)) tryMount();
      }).observe(document.body, { childList: true, subtree: true });
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 600); });
  } else {
    setTimeout(boot, 600);
  }
})();
'''

Path("public").mkdir(exist_ok=True)
Path("public/ace-xpu-lora-picker.js").write_text(js)

# Inject into every HTML shell we can find (Vite root + public)
for hp in ["index.html", "public/index.html"]:
    p = Path(hp)
    if not p.exists():
        continue
    h = p.read_text()
    for script in [
        "ace-xpu-lora-picker.js",
        "ace-xpu-console.js",
        "ace-xpu-restart.js",
        "ace-xpu-draft.js",
    ]:
        tag = f'<script src="/{script}"></script>'
        if script not in h:
            if "</body>" in h:
                h = h.replace("</body>", tag + "\n</body>")
            else:
                h += "\n" + tag + "\n"
    p.write_text(h)
    print(f"Ensured scripts in {hp}")

print("lora-picker OK — sidebar append")
