#!/usr/bin/env python3
"""LoRA checkpoint picker for ace-step-ui (Intel XPU Docker).

- Extends server/src/routes/lora.ts with GET /api/lora/list
- Improves load to unload-first when switching adapters
- Injects floating picker UI (public/ace-xpu-lora-picker.js)
"""
from pathlib import Path
import re

lora_ts = Path("server/src/routes/lora.ts")
text = lora_ts.read_text()

if "GET /api/lora/list" not in text and "/list" not in text:
    # Ensure fs imports
    if "from 'fs'" not in text and 'from "fs"' not in text:
        text = (
            "import { existsSync, readdirSync, statSync } from 'fs';\n"
            "import path from 'path';\n"
            + text
        )

    LIST_AND_IMPROVED = r'''
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
    // Prefer .../adapter as the load path when present
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
      } catch {
        /* skip */
      }
    }
  } catch {
    /* skip */
  }
  return out;
}

// GET /api/lora/list — Discover adapters under LORA_OUTPUT_DIR
router.get('/list', authMiddleware, async (_req: AuthenticatedRequest, res: Response) => {
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
      const ea = a.epoch ?? -1;
      const eb = b.epoch ?? -1;
      return eb - ea;
    });
    res.json({ adapters: found, current: loraState, roots: loraRoots() });
  } catch (error) {
    console.error('[LoRA] List error:', error);
    res.status(500).json({ error: error instanceof Error ? error.message : 'Failed to list LoRAs' });
  }
});
'''

    # Insert helpers + list route before export default
    text = text.replace(
        "export default router;",
        LIST_AND_IMPROVED + "\nexport default router;\n",
    )
    print("Added GET /api/lora/list")
else:
    print("list route already present")

# Improve /load to unload first when switching (reduces multi-adapter ghosts)
if "unload before load" not in text:
    old_load = """    const client = await getGradioClient();
    const result = await client.predict('/load_lora', [lora_path]);
    const status = (result.data as unknown[])[0] as string;

    loraState = { loaded: true, active: true, scale: loraState.scale, path: lora_path };

    res.json({ message: status, lora_path, loaded: true });"""
    new_load = """    const client = await getGradioClient();

    // unload before load when switching adapters (ACE-Step can stack adapters)
    if (loraState.loaded && loraState.path && loraState.path !== lora_path) {
      try {
        await client.predict('/unload_lora', []);
        console.log('[LoRA] Unloaded previous before switch');
      } catch (e) {
        console.warn('[LoRA] Pre-load unload failed (continuing):', e);
      }
    }

    const result = await client.predict('/load_lora', [lora_path]);
    const status = (result.data as unknown[])[0] as string;

    // enable use_lora
    try {
      await client.predict('/set_use_lora', [true]);
    } catch (e) {
      console.warn('[LoRA] set_use_lora failed:', e);
    }

    loraState = { loaded: true, active: true, scale: loraState.scale, path: lora_path };

    res.json({ message: status, lora_path, loaded: true, active: true });"""
    if old_load in text:
        text = text.replace(old_load, new_load)
        print("Improved /load with unload-before-switch")
    else:
        print("WARN: load body not matched for unload-before-switch")

lora_ts.write_text(text)
print("lora.ts updated")

# --- Floating picker UI ---
js = r'''(function () {
  var KEY = "ace-xpu-lora-picker";
  function token() {
    try {
      for (var i = 0; i < 4; i++) {
        var keys = ["token", "authToken", "access_token", "jwt"];
        for (var k of keys) {
          var v = localStorage.getItem(k);
          if (v && v.length > 12) return v.replace(/^Bearer\s+/i, "");
        }
      }
    } catch (e) {}
    return null;
  }
  function authHeaders() {
    var t = token();
    var h = { "Content-Type": "application/json" };
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }
  async function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
    var r = await fetch(path, opts);
    var j = null;
    try {
      j = await r.json();
    } catch (e) {
      j = { error: await r.text() };
    }
    if (!r.ok) throw new Error((j && (j.error || j.detail || j.message)) || r.statusText);
    return j;
  }

  function ensure() {
    if (document.getElementById("ace-xpu-lora-panel")) return;
    var panel = document.createElement("div");
    panel.id = "ace-xpu-lora-panel";
    panel.style.cssText =
      "position:fixed;bottom:72px;right:16px;z-index:99998;width:min(340px,calc(100vw - 24px));" +
      "background:#121212;color:#eee;border:1px solid #333;border-radius:12px;padding:12px;" +
      "font:13px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.45)";
    panel.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
      "<strong>LoRA picker</strong>" +
      '<button id="ace-lora-refresh" style="background:#333;color:#fff;border:0;border-radius:6px;padding:4px 8px;cursor:pointer">Refresh</button>' +
      "</div>" +
      '<select id="ace-lora-select" style="width:100%;margin-bottom:8px;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:6px"></select>' +
      '<label style="display:flex;align-items:center;gap:8px;margin-bottom:8px">Scale ' +
      '<input id="ace-lora-scale" type="range" min="0" max="1" step="0.05" value="0.8" style="flex:1"/>' +
      '<span id="ace-lora-scale-val">0.80</span></label>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button id="ace-lora-load" style="flex:1;background:#1db954;color:#000;border:0;border-radius:8px;padding:8px;font-weight:700;cursor:pointer">Load</button>' +
      '<button id="ace-lora-unload" style="flex:1;background:#333;color:#fff;border:0;border-radius:8px;padding:8px;cursor:pointer">Unload</button>' +
      "</div>" +
      '<div id="ace-lora-status" style="margin-top:8px;font-size:12px;color:#9ab;word-break:break-all">Log in, then Refresh</div>';
    document.body.appendChild(panel);

    var sel = document.getElementById("ace-lora-select");
    var scale = document.getElementById("ace-lora-scale");
    var scaleVal = document.getElementById("ace-lora-scale-val");
    var status = document.getElementById("ace-lora-status");
    scale.oninput = function () {
      scaleVal.textContent = Number(scale.value).toFixed(2);
    };

    async function refresh() {
      status.textContent = "Listing…";
      try {
        var data = await api("/api/lora/list");
        sel.innerHTML = "";
        var adapters = data.adapters || [];
        if (!adapters.length) {
          sel.innerHTML = '<option value="">(no adapters found)</option>';
          status.textContent = "No adapters under " + (data.roots || []).join(", ");
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
          sel.value = data.current.path;
          if (typeof data.current.scale === "number") {
            scale.value = String(data.current.scale);
            scaleVal.textContent = Number(data.current.scale).toFixed(2);
          }
          status.textContent =
            (data.current.loaded ? "Loaded: " : "Not loaded. Last: ") + data.current.path;
        } else {
          status.textContent = adapters.length + " adapter(s) found";
        }
      } catch (e) {
        status.textContent = String(e.message || e);
      }
    }

    document.getElementById("ace-lora-refresh").onclick = refresh;
    document.getElementById("ace-lora-load").onclick = async function () {
      var p = sel.value;
      if (!p) return alert("Pick an adapter");
      if (!token()) return alert("Log in first");
      status.textContent = "Loading…";
      try {
        await api("/api/lora/scale", {
          method: "POST",
          body: JSON.stringify({ scale: Number(scale.value) }),
        }).catch(function () {});
        var r = await api("/api/lora/load", {
          method: "POST",
          body: JSON.stringify({ lora_path: p }),
        });
        status.textContent = "Loaded: " + p + (r.message ? " — " + r.message : "");
      } catch (e) {
        status.textContent = "Load failed: " + (e.message || e);
      }
    };
    document.getElementById("ace-lora-unload").onclick = async function () {
      if (!token()) return alert("Log in first");
      status.textContent = "Unloading…";
      try {
        var r = await api("/api/lora/unload", { method: "POST", body: "{}" });
        status.textContent = "Unloaded" + (r.message ? " — " + r.message : "");
      } catch (e) {
        status.textContent = "Unload failed: " + (e.message || e);
      }
    };

    setTimeout(refresh, 800);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(ensure, 1200);
    });
  } else {
    setTimeout(ensure, 1200);
  }
})();
'''

Path("public").mkdir(exist_ok=True)
Path("public/ace-xpu-lora-picker.js").write_text(js)
print("Wrote public/ace-xpu-lora-picker.js")

for hp in ["index.html", "public/index.html"]:
    p = Path(hp)
    if not p.exists():
        continue
    h = p.read_text()
    if "ace-xpu-lora-picker" in h:
        print(f"{hp} already has lora picker script")
        continue
    tag = '<script src="/ace-xpu-lora-picker.js"></script>'
    if "</body>" in h:
        h = h.replace("</body>", tag + "</body>")
    else:
        h = h + "\n" + tag + "\n"
    p.write_text(h)
    print(f"Injected picker into {hp}")

print("lora-picker OK")
