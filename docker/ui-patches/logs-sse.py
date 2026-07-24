#!/usr/bin/env python3
"""Wire SSE log streaming (/api/logs/stream) + floating console panel.

Open when OPEN_LOCAL_AUTH=true (default for this Docker stack).
"""
from pathlib import Path

Path("server/src/routes/logs.ts").write_text(r'''
import { Router, Response, Request } from "express";
import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import { authMiddleware, AuthenticatedRequest } from "../middleware/auth.js";
import jwt from "jsonwebtoken";

const router = Router();

const JWT_SECRET = process.env.JWT_SECRET || "ace-step-ui-local-secret";
const XPU_NAME = process.env.XPU_CONTAINER_NAME || "acestep-xpu";
const UI_NAME = process.env.UI_CONTAINER_NAME || "acestep-ui";
const ENABLE = (process.env.ENABLE_LOG_STREAM || "true").toLowerCase() !== "false";

function openLocalAuth(): boolean {
  const v = (process.env.OPEN_LOCAL_AUTH || "true").toLowerCase();
  return v !== "false" && v !== "0" && v !== "no" && v !== "off";
}

function shouldFilterLine(line: string, filterNoise: boolean): boolean {
  if (!filterNoise) return false;
  if (/audio_code_/i.test(line)) return true;
  if (/formatted_prompt/i.test(line)) return true;
  if (line.length > 4000) return true;
  return false;
}

function classify(line: string): "error" | "warn" | "info" {
  if (/\b(ERROR|Error|Traceback|Exception|failed|FATAL)\b/i.test(line)) return "error";
  if (/\b(WARNING|WARN|deprecated)\b/i.test(line)) return "warn";
  return "info";
}

function authFromQueryOrHeader(req: Request): { ok: boolean; userId?: string } {
  // Local Docker: no token required
  if (openLocalAuth()) {
    return { ok: true, userId: "local-docker-user" };
  }
  try {
    const hdr = req.headers.authorization;
    let token = "";
    if (hdr?.startsWith("Bearer ")) token = hdr.slice(7);
    if (!token && typeof req.query.token === "string") token = req.query.token;
    if (!token) return { ok: false };
    const payload = jwt.verify(token, JWT_SECRET) as { userId?: string; id?: string; sub?: string };
    return { ok: true, userId: payload.userId || payload.id || payload.sub };
  } catch {
    return { ok: false };
  }
}

router.get("/stream", (req: Request, res: Response) => {
  if (!ENABLE) {
    res.status(403).json({ error: "Log streaming disabled" });
    return;
  }

  const auth = authFromQueryOrHeader(req);
  if (!auth.ok) {
    res.status(401).json({ error: "Unauthorized — pass ?token=JWT or Authorization header" });
    return;
  }

  const source = String(req.query.source || "xpu").toLowerCase();
  const filterNoise = String(req.query.filter ?? "1") !== "0";
  const tail = Math.min(Math.max(parseInt(String(req.query.tail || "120"), 10) || 120, 20), 500);

  const containers: string[] = [];
  if (source === "ui") containers.push(UI_NAME);
  else if (source === "all") containers.push(XPU_NAME, UI_NAME);
  else containers.push(XPU_NAME);

  res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders?.();

  const send = (event: string, data: object) => {
    try {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    } catch {
      /* client gone */
    }
  };

  send("status", {
    message: `Streaming ${containers.join(", ")} (tail=${tail}, filter=${filterNoise})`,
    containers,
  });

  const children: ChildProcessWithoutNullStreams[] = [];
  let closed = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    for (const c of children) {
      try {
        c.kill("SIGTERM");
      } catch {
        /* ignore */
      }
    }
  };

  req.on("close", cleanup);
  req.on("error", cleanup);

  for (const name of containers) {
    const child = spawn(
      "docker",
      ["logs", "-f", "--tail", String(tail), "--timestamps", name],
      { stdio: ["ignore", "pipe", "pipe"] }
    );
    children.push(child);

    const onChunk = (buf: Buffer, stream: "stdout" | "stderr") => {
      const text = buf.toString("utf8");
      for (const raw of text.split(/\r?\n/)) {
        if (!raw) continue;
        if (shouldFilterLine(raw, filterNoise)) continue;
        send("log", {
          container: name,
          stream,
          level: classify(raw),
          line: raw.length > 2000 ? raw.slice(0, 2000) + "…" : raw,
          ts: Date.now(),
        });
      }
    };

    child.stdout.on("data", (b) => onChunk(b, "stdout"));
    child.stderr.on("data", (b) => onChunk(b, "stderr"));
    child.on("error", (err) => {
      send("error", {
        message: `Failed to stream ${name}: ${err.message}. Is docker.sock mounted?`,
      });
    });
    child.on("close", (code) => {
      send("status", { message: `docker logs exited for ${name} (code=${code})` });
    });
  }

  const heartbeat = setInterval(() => {
    if (closed) {
      clearInterval(heartbeat);
      return;
    }
    send("ping", { t: Date.now() });
  }, 15000);

  req.on("close", () => clearInterval(heartbeat));
});

router.get("/tail", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  if (!ENABLE) {
    res.status(403).json({ error: "Log streaming disabled" });
    return;
  }
  const source = String(req.query.source || "xpu");
  const name = source === "ui" ? UI_NAME : XPU_NAME;
  const n = Math.min(Math.max(parseInt(String(req.query.n || "80"), 10) || 80, 1), 300);
  const { execFile } = await import("child_process");
  const { promisify } = await import("util");
  const execFileAsync = promisify(execFile);
  try {
    const { stdout, stderr } = await execFileAsync(
      "docker",
      ["logs", "--tail", String(n), "--timestamps", name],
      { timeout: 15000, maxBuffer: 4 * 1024 * 1024 }
    );
    res.type("text/plain").send((stdout || "") + (stderr || ""));
  } catch (err: any) {
    res.status(500).json({
      error: "Failed to read logs",
      detail: String(err?.stderr || err?.message || err),
    });
  }
});

export default router;
''')
print("Wrote server/src/routes/logs.ts (open auth)")

idx = Path("server/src/index.ts")
it = idx.read_text()
if "logsRoutes" not in it and "routes/logs" not in it:
    if "import systemRoutes" in it:
        it = it.replace(
            "import systemRoutes from './routes/system.js';",
            "import systemRoutes from './routes/system.js';\nimport logsRoutes from './routes/logs.js';",
        )
    else:
        it = "import logsRoutes from './routes/logs.js';\n" + it

    if "app.use('/api/system'" in it:
        it = it.replace(
            "app.use('/api/system', systemRoutes);",
            "app.use('/api/system', systemRoutes);\napp.use('/api/logs', logsRoutes);",
        )
    elif "app.use('/api/settings'" in it:
        it = it.replace(
            "app.use('/api/settings', settingsRoutes);",
            "app.use('/api/settings', settingsRoutes);\napp.use('/api/logs', logsRoutes);",
        )
    else:
        it = it.replace(
            "app.use('/api/auth', authRoutes);",
            "app.use('/api/auth', authRoutes);\napp.use('/api/logs', logsRoutes);",
        )
    idx.write_text(it)
    print("Wired /api/logs into index.ts")
else:
    print("logs routes already wired")

js = r'''(function () {
  const FILTER_KEY = "ace-console-filter";
  const SOURCE_KEY = "ace-console-source";

  function el(tag, css, text) {
    const n = document.createElement(tag);
    if (css) n.style.cssText = css;
    if (text != null) n.textContent = text;
    return n;
  }

  let es = null;
  let paused = false;
  let lines = [];
  const MAX = 800;

  function ensure() {
    if (document.getElementById("ace-xpu-console-root")) return;

    const root = el(
      "div",
      "position:fixed;left:0;right:0;bottom:0;z-index:99998;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;"
    );
    root.id = "ace-xpu-console-root";

    const toggle = el(
      "button",
      "position:fixed;bottom:16px;left:16px;z-index:99999;background:#111;color:#1db954;border:1px solid #1db954;border-radius:999px;padding:8px 14px;font-weight:700;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.4);"
    );
    toggle.id = "ace-xpu-console-toggle";
    toggle.textContent = "Console";

    const panel = el(
      "div",
      "display:none;height:280px;background:#0b0b0b;color:#d4d4d4;border-top:1px solid #333;flex-direction:column;"
    );
    panel.id = "ace-xpu-console-panel";

    const bar = el(
      "div",
      "display:flex;gap:8px;align-items:center;padding:6px 10px;background:#161616;border-bottom:1px solid #2a2a2a;flex-wrap:wrap;"
    );

    const status = el("span", "color:#888;margin-right:auto;", "Disconnected");
    status.id = "ace-xpu-console-status";

    const sourceSel = document.createElement("select");
    sourceSel.style.cssText = "background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:2px 6px;";
    ["xpu", "ui", "all"].forEach((v) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = v === "xpu" ? "acestep-xpu" : v === "ui" ? "acestep-ui" : "all";
      sourceSel.appendChild(o);
    });
    sourceSel.value = localStorage.getItem(SOURCE_KEY) || "xpu";

    const filterCb = document.createElement("label");
    filterCb.style.cssText = "display:flex;align-items:center;gap:4px;color:#aaa;cursor:pointer;";
    const filterInput = document.createElement("input");
    filterInput.type = "checkbox";
    filterInput.checked = localStorage.getItem(FILTER_KEY) !== "0";
    filterCb.appendChild(filterInput);
    filterCb.appendChild(document.createTextNode("Filter noise"));

    const btn = (label) => {
      const b = el(
        "button",
        "background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:3px 10px;cursor:pointer;"
      );
      b.textContent = label;
      return b;
    };

    const connectBtn = btn("Connect");
    const pauseBtn = btn("Pause");
    const clearBtn = btn("Clear");
    const copyBtn = btn("Copy");

    bar.appendChild(status);
    bar.appendChild(sourceSel);
    bar.appendChild(filterCb);
    bar.appendChild(connectBtn);
    bar.appendChild(pauseBtn);
    bar.appendChild(clearBtn);
    bar.appendChild(copyBtn);

    const pre = el(
      "div",
      "flex:1;overflow:auto;padding:8px 10px;white-space:pre-wrap;word-break:break-all;line-height:1.35;"
    );
    pre.id = "ace-xpu-console-body";

    panel.appendChild(bar);
    panel.appendChild(pre);
    root.appendChild(panel);
    document.body.appendChild(root);
    document.body.appendChild(toggle);

    let open = false;
    toggle.onclick = () => {
      open = !open;
      panel.style.display = open ? "flex" : "none";
      toggle.textContent = open ? "Console ▾" : "Console";
      if (open && !es) connect();
    };

    function append(level, line, container) {
      if (paused) return;
      const color =
        level === "error" ? "#ff6b6b" : level === "warn" ? "#ffd43b" : "#adb5bd";
      const prefix = container ? `[${container}] ` : "";
      lines.push({ level, line: prefix + line, color });
      if (lines.length > MAX) lines = lines.slice(-MAX);
      const row = el("div", `color:${color}`);
      row.textContent = prefix + line;
      pre.appendChild(row);
      while (pre.childNodes.length > MAX) pre.removeChild(pre.firstChild);
      pre.scrollTop = pre.scrollHeight;
    }

    function disconnect() {
      if (es) {
        try {
          es.close();
        } catch (e) {}
        es = null;
      }
      status.textContent = "Disconnected";
      status.style.color = "#888";
      connectBtn.textContent = "Connect";
    }

    function connect() {
      disconnect();
      localStorage.setItem(SOURCE_KEY, sourceSel.value);
      localStorage.setItem(FILTER_KEY, filterInput.checked ? "1" : "0");
      // No token required when OPEN_LOCAL_AUTH=true on the server
      const q = new URLSearchParams({
        source: sourceSel.value,
        filter: filterInput.checked ? "1" : "0",
        tail: "150",
      });
      const url = `/api/logs/stream?${q.toString()}`;
      status.textContent = "Connecting…";
      status.style.color = "#ffd43b";
      es = new EventSource(url);

      es.addEventListener("status", (ev) => {
        try {
          const d = JSON.parse(ev.data);
          status.textContent = d.message || "Connected";
          status.style.color = "#1db954";
          append("info", d.message || "status", "sys");
        } catch (e) {}
      });
      es.addEventListener("log", (ev) => {
        try {
          const d = JSON.parse(ev.data);
          append(d.level || "info", d.line || "", d.container || "");
        } catch (e) {}
      });
      es.addEventListener("error", (ev) => {
        try {
          const d = JSON.parse(ev.data);
          append("error", d.message || "stream error", "sys");
          status.textContent = d.message || "Error";
          status.style.color = "#ff6b6b";
        } catch (e) {
          if (es && es.readyState === EventSource.CLOSED) {
            status.textContent = "Disconnected";
            status.style.color = "#888";
            connectBtn.textContent = "Connect";
          }
        }
      });
      es.addEventListener("ping", () => {});
      es.onerror = () => {
        if (es && es.readyState === EventSource.CLOSED) {
          status.textContent = "Stream closed";
          status.style.color = "#ff6b6b";
          connectBtn.textContent = "Connect";
          es = null;
        }
      };
      connectBtn.textContent = "Disconnect";
    }

    connectBtn.onclick = () => {
      if (es) disconnect();
      else connect();
    };
    pauseBtn.onclick = () => {
      paused = !paused;
      pauseBtn.textContent = paused ? "Resume" : "Pause";
    };
    clearBtn.onclick = () => {
      lines = [];
      pre.innerHTML = "";
    };
    copyBtn.onclick = async () => {
      const text = lines.map((l) => l.line).join("\n");
      try {
        await navigator.clipboard.writeText(text);
        status.textContent = "Copied " + lines.length + " lines";
      } catch (e) {
        status.textContent = "Copy failed";
      }
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(ensure, 1200));
  } else {
    setTimeout(ensure, 1200);
  }
})();
'''

Path("public").mkdir(exist_ok=True)
Path("public/ace-xpu-console.js").write_text(js)
print("Wrote public/ace-xpu-console.js (no token)")

for hp in ["index.html", "public/index.html"]:
    p = Path(hp)
    if not p.exists():
        continue
    h = p.read_text()
    if "ace-xpu-console" in h:
        print(f"{hp} already has console script")
        continue
    snippet = '<script src="/ace-xpu-console.js"></script>'
    if "</body>" in h:
        h = h.replace("</body>", snippet + "</body>")
    else:
        h = h + snippet
    p.write_text(h)
    print(f"Injected console into {hp}")

print("SSE log streaming patch complete")
