#!/usr/bin/env python3
"""LoRA checkpoint picker for ace-step-ui (Intel XPU Docker).

- Extends server/src/routes/lora.ts with GET /api/lora/list
- Improves load to unload-first when switching adapters
- Injects adapter dropdown INTO the existing left-sidebar LoRA settings
  (no floating panel)
"""
from pathlib import Path
import re

lora_ts = Path("server/src/routes/lora.ts")
text = lora_ts.read_text()

if "GET /api/lora/list" not in text and "router.get('/list'" not in text and 'router.get("/list"' not in text:
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

    text = text.replace(
        "export default router;",
        LIST_AND_IMPROVED + "\nexport default router;\n",
    )
    print("Added GET /api/lora/list")
else:
    print("list route already present")

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

# --- Inline left-menu picker (no floating panel) ---
js = r'''(function () {
  var HOST_ID = "ace-xpu-lora-inline";

  function token() {
    try {
      var keys = ["token", "authToken", "access_token", "jwt"];
      for (var i = 0; i < keys.length; i++) {
        var v = localStorage.getItem(keys[i]);
        if (v && v.length > 12) return v.replace(/^Bearer\s+/i, "");
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

  /** Find the built-in LoRA block in the left sidebar / settings. */
  function findLoraAnchor() {
    var root =
      document.querySelector("aside") ||
      document.querySelector("[class*=\"sidebar\"]") ||
      document.querySelector("nav") ||
      document.body;

    var candidates = root.querySelectorAll("label, h2, h3, h4, span, div, p, button");
    for (var i = 0; i < candidates.length; i++) {
      var el = candidates[i];
      var t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (!t || t.length > 48) continue;
      if (/^lora$/i.test(t) || /^use lora$/i.test(t) || /lora scale/i.test(t) ||
          /load lora/i.test(t) || /lora path/i.test(t) || /adapter/i.test(t) && /lora/i.test(t)) {
        // Prefer a stable parent that holds the LoRA controls
        var block = el.closest("section, fieldset, [class*=\"panel\"], [class*=\"section\"], [class*=\"card\"], form, div");
        return block || el.parentElement || el;
      }
    }
    // Fallback: any input that looks like a path field near "lora"
    var inputs = document.querySelectorAll("input[type=text], input:not([type])");
    for (var j = 0; j < inputs.length; j++) {
      var ph = (inputs[j].getAttribute("placeholder") || "").toLowerCase();
      var name = (inputs[j].getAttribute("name") || "").toLowerCase();
      if (ph.indexOf("lora") >= 0 || name.indexOf("lora") >= 0 || ph.indexOf("adapter") >= 0) {
        return inputs[j].closest("div, section, label") || inputs[j].parentElement;
      }
    }
    return null;
  }

  function removeFloatingPanel() {
    var old = document.getElementById("ace-xpu-lora-panel");
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

  function mountInline(anchor) {
    if (document.getElementById(HOST_ID)) return;
    removeFloatingPanel();

    var host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("data-ace-xpu", "lora-inline");
    host.style.cssText =
      "margin:10px 0 12px;padding:10px 0 0;border-top:1px solid rgba(255,255,255,0.08);";

    host.innerHTML =
      '<div style="font-size:12px;font-weight:600;opacity:0.9;margin-bottom:6px">Trained adapters</div>' +
      '<select id="ace-lora-select" style="width:100%;box-sizing:border-box;margin-bottom:8px;' +
      "background:transparent;color:inherit;border:1px solid rgba(255,255,255,0.15);" +
      'border-radius:8px;padding:7px 8px;font:inherit"></select>' +
      '<div style="display:flex;gap:6px;margin-bottom:6px">' +
      '<button type="button" id="ace-lora-refresh" style="flex:0 0 auto;padding:6px 10px;border-radius:8px;' +
      "border:1px solid rgba(255,255,255,0.15);background:transparent;color:inherit;cursor:pointer;font:inherit">Refresh</button>" +
      '<button type="button" id="ace-lora-load" style="flex:1;padding:6px 10px;border-radius:8px;border:0;' +
      'background:#1db954;color:#000;font-weight:700;cursor:pointer;font:inherit">Load</button>' +
      '<button type="button" id="ace-lora-unload" style="flex:1;padding:6px 10px;border-radius:8px;' +
      "border:1px solid rgba(255,255,255,0.15);background:transparent;color:inherit;cursor:pointer;font:inherit">Unload</button>' +
      "</div>" +
      '<div id="ace-lora-status" style="font-size:11px;opacity:0.75;word-break:break-all;line-height:1.35">' +
      "Pick an adapter from /app/lora_output</div>";

    // Insert after the existing LoRA controls so it feels native
    if (anchor.parentNode) {
      if (anchor.nextSibling) anchor.parentNode.insertBefore(host, anchor.nextSibling);
      else anchor.parentNode.appendChild(host);
    } else {
      anchor.appendChild(host);
    }

    var sel = host.querySelector("#ace-lora-select");
    var status = host.querySelector("#ace-lora-status");

    async function refresh() {
      status.textContent = "Listing…";
      try {
        if (!token()) {
          status.textContent = "Log in to list trained adapters";
          return;
        }
        var data = await api("/api/lora/list");
        sel.innerHTML = "";
        var adapters = data.adapters || [];
        if (!adapters.length) {
          sel.innerHTML = '<option value="">(no adapters found)</option>';
          status.textContent = "Train a LoRA first — nothing under " + (data.roots || []).join(", ");
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
          try {
            sel.value = data.current.path;
          } catch (e) {}
          status.textContent =
            (data.current.loaded ? "Loaded: " : "Listed. Last: ") + data.current.path;
        } else {
          status.textContent = adapters.length + " adapter(s)";
        }

        // If native path input exists, keep it in sync when user picks
        var pathInput = document.querySelector(
          'input[placeholder*="lora" i], input[placeholder*="adapter" i], input[name*="lora" i]'
        );
        if (pathInput && sel.value) {
          pathInput.value = sel.value;
          pathInput.dispatchEvent(new Event("input", { bubbles: true }));
          pathInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } catch (e) {
        status.textContent = String(e.message || e);
      }
    }

    sel.addEventListener("change", function () {
      var pathInput = document.querySelector(
        'input[placeholder*="lora" i], input[placeholder*="adapter" i], input[name*="lora" i]'
      );
      if (pathInput && sel.value) {
        pathInput.value = sel.value;
        pathInput.dispatchEvent(new Event("input", { bubbles: true }));
        pathInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    host.querySelector("#ace-lora-refresh").onclick = refresh;
    host.querySelector("#ace-lora-load").onclick = async function () {
      var p = sel.value;
      if (!p) return alert("Pick an adapter");
      if (!token()) return alert("Log in first");
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
      if (!token()) return alert("Log in first");
      status.textContent = "Unloading…";
      try {
        var r = await api("/api/lora/unload", { method: "POST", body: "{}" });
        status.textContent = "Unloaded" + (r.message ? " — " + r.message : "");
      } catch (e) {
        status.textContent = "Unload failed: " + (e.message || e);
      }
    };

    setTimeout(refresh, 400);
  }

  function tryMount() {
    removeFloatingPanel();
    if (document.getElementById(HOST_ID)) return true;
    var anchor = findLoraAnchor();
    if (!anchor) return false;
    mountInline(anchor);
    return true;
  }

  function boot() {
    if (tryMount()) return;
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (tryMount() || tries > 40) clearInterval(iv);
    }, 500);

    // SPA navigation / React re-renders
    try {
      var obs = new MutationObserver(function () {
        removeFloatingPanel();
        if (!document.getElementById(HOST_ID)) tryMount();
      });
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(boot, 800);
    });
  } else {
    setTimeout(boot, 800);
  }
})();
'''

Path("public").mkdir(exist_ok=True)
Path("public/ace-xpu-lora-picker.js").write_text(js)
print("Wrote public/ace-xpu-lora-picker.js (inline left-menu)")

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

print("lora-picker OK — inline left menu")
