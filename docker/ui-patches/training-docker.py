#!/usr/bin/env python3
"""Patch training.ts — blacklist missing Gradio names; no bare predict throws."""
from pathlib import Path
import re

training = Path("server/src/routes/training.ts")
text = training.read_text()

if "fileURLToPath" not in text:
    text = "import { fileURLToPath } from 'url';\n" + text

# Remove any previous helper copies to avoid duplicates, then inject once
text = re.sub(
    r"/\*\* ACE-Step-Intel-XPU-Docker training helpers \*/[\s\S]*?async function safeGradioPredict[\s\S]*?\n\}\n",
    "",
    text,
)
text = re.sub(
    r"/\*\* Docker / XPU path helpers[\s\S]*?async function safeGradioPredict[\s\S]*?\n\}\n",
    "",
    text,
)

HELPER = r'''
/** ACE-Step-Intel-XPU-Docker training helpers */
const __aceDirname = path.dirname(fileURLToPath(import.meta.url));

/** Endpoints that do NOT exist as named Gradio API on ACE-Step 1.5 (your /gradio_api/info). */
const GRADIO_ENDPOINT_BLACKLIST = new Set([
  "/init_service_wrapper",
  "init_service_wrapper",
  "/auto_label_all",
  "auto_label_all",
  "/auto_label",
  "auto_label",
]);

function xpuContainer(): string {
  return process.env.XPU_CONTAINER_NAME || "acestep-xpu";
}

function normalizeTrainingPath(input: string | undefined | null, fallback: string): string {
  let s = (input && String(input).trim()) || fallback;
  s = s.split("/app/ACE-Step-1.5/datasets").join("/app/datasets");
  s = s.split("ACE-Step-1.5/datasets").join("/app/datasets");
  if (s === "./datasets" || s === "datasets") s = "/app/datasets";
  if (s === "./datasets/preprocessed_tensors" || s.endsWith("datasets/preprocessed_tensors")) {
    s = "/app/datasets/preprocessed_tensors";
  }
  if (s === "./lora_output" || s === "lora_output") s = "/app/lora_output";
  if (!s.startsWith("/") && !s.startsWith("./")) s = path.posix.join("/app/datasets", s);
  if (s.startsWith("./")) s = path.posix.join("/app", s.slice(2));
  return s;
}

async function safeGradioPredict(
  endpoint: string,
  args: unknown[]
): Promise<{ ok: true; data: unknown[]; endpoint: string } | { ok: false; error: string; endpoint: string }> {
  const ep0 = endpoint.startsWith("/") ? endpoint : "/" + endpoint;

  if (GRADIO_ENDPOINT_BLACKLIST.has(endpoint) || GRADIO_ENDPOINT_BLACKLIST.has(ep0)) {
    console.warn("[Training] Skipping blacklisted Gradio endpoint", ep0);
    return {
      ok: false,
      error: "Endpoint not available on this ACE-Step Gradio API build (blacklisted)",
      endpoint: ep0,
    };
  }

  let client: any;
  try {
    client = await getGradioClient();
  } catch (e: any) {
    return { ok: false, error: String(e?.message || e), endpoint: ep0 };
  }

  const variants = [ep0];
  if (!ep0.endsWith("_1")) variants.push(ep0 + "_1");

  let lastErr = "";
  for (const ep of variants) {
    try {
      console.log("[Training] Gradio predict", ep);
      // Explicit .then/.catch so Gradio client cannot surface unhandledRejection
      const result: any = await Promise.resolve(client.predict(ep, args)).catch((err: any) => {
        throw err;
      });
      return { ok: true, data: (result?.data as unknown[]) || [], endpoint: ep };
    } catch (e: any) {
      lastErr = String(e?.message || e);
      console.warn("[Training] Gradio predict failed", ep, lastErr);
      if (!lastErr.includes("no endpoint matching")) {
        return { ok: false, error: lastErr, endpoint: ep };
      }
    }
  }
  return { ok: false, error: lastErr || "no endpoint", endpoint: ep0 };
}

'''

if "function getAceStepDir" in text:
    start = text.find("function getAceStepDir")
    i = text.find("{", start)
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    text = text[:j] + "\n" + HELPER + text[j:]
else:
    text = HELPER + text

text = text.replace(
    "return path.resolve(config.datasets.dir, '..');",
    'return process.env.ACESTEP_PATH || path.resolve(config.datasets.dir, "..") || "/app";',
)
text = text.replace("path.resolve(__dirname,", "path.resolve(__aceDirname,")

# Rewrite remaining client.predict to safeGradioPredict
text2, n = re.subn(
    r"await\s+client\.predict\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\[[\s\S]*?\])\s*\)",
    lambda m: f"await safeGradioPredict('{m.group(1)}', {m.group(2)})",
    text,
)
print(f"client.predict -> safeGradioPredict: {n}")
text = text2

# Also catch client.predict with template or variable first arg — leave as-is if any

# Fix result.data pattern after safeGradioPredict
text = re.sub(
    r"const result = await safeGradioPredict\(([^;]+)\);\s*const data = result\.data as unknown\[\];",
    r"const __pred = await safeGradioPredict(\1);\n    if (!__pred.ok) { res.status(502).json({ error: 'Gradio endpoint failed', detail: __pred.error, endpoint: __pred.endpoint }); return; }\n    const data = __pred.data;",
    text,
)

# Any remaining `result = await safeGradioPredict` then `result.data` without ok check:
# broader fix for init-model style that does predict and uses result without ok
text = re.sub(
    r"(const result = await safeGradioPredict\([^;]+\);)\s*\n(\s*)(const data = \(result\.data)",
    r"\1\n\2if (!(result as any).ok) { res.status(502).json({ error: 'Gradio endpoint failed', detail: (result as any).error, endpoint: (result as any).endpoint }); return; }\n\2const data = ((result as any).data",
    text,
)

def replace_route(src: str, path: str, new_body: str):
    for quote in ("'", '"'):
        needle = f"router.post({quote}{path}{quote}"
        start = src.find(needle)
        if start >= 0:
            break
    else:
        return src, False
    i = src.find("{", start)
    depth = 0
    in_s = in_d = in_t = False
    esc = False
    j = i
    while j < len(src):
        c = src[j]
        if in_s:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == "'": in_s = False
        elif in_d:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_d = False
        elif in_t:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == "`": in_t = False
        else:
            if c == "'": in_s = True
            elif c == '"': in_d = True
            elif c == "`": in_t = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    if end < len(src) and src[end] == ")": end += 1
                    if end < len(src) and src[end] == ";": end += 1
                    return src[:start] + new_body.strip() + src[end:], True
        j += 1
    return src, False

INIT = r'''
router.post("/init-model", authMiddleware, async (_req: AuthenticatedRequest, res: Response) => {
  res.status(200).json({
    status: "Model service assumed ready (container auto-init)",
    modelReady: true,
    soft: true,
    hint: "DiT/LM already loaded by acestep-xpu; Init Model is a no-op on this stack",
  });
});
'''

AUTO = r'''
router.post("/auto-label", authMiddleware, async (_req: AuthenticatedRequest, res: Response) => {
  res.status(501).json({
    error: "Auto-label API not exposed on this ACE-Step Gradio build",
    hint: "Use Gradio UI :8001 or label samples manually",
  });
});
'''

text, ok = replace_route(text, "/init-model", INIT)
print("init-model route", ok)
if not ok:
    # force: strip any remaining safeGradioPredict('/init_service_wrapper'
    pass

text, ok = replace_route(text, "/auto-label", AUTO)
print("auto-label route", ok)

# Nuclear: any remaining init_service_wrapper string in predict calls -> blacklist already handles
# But if code does: const result = await safeGradioPredict('/init_service_wrapper'...
# and then uses result without checking ok, still throws when accessing?
# Unhandled rejection was from predict itself - blacklist prevents predict call.

# Replace init-model body if route replace failed but still has init_service_wrapper
if "init_service_wrapper" in text:
    # Replace the predict call sites with immediate soft result
    text = text.replace(
        "await safeGradioPredict('/init_service_wrapper'",
        "await safeGradioPredict('/__blacklisted_init_service_wrapper'",
    )
    text = text.replace(
        'await safeGradioPredict("/init_service_wrapper"',
        'await safeGradioPredict("/__blacklisted_init_service_wrapper"',
    )
    GRADIO_ENDPOINT_BLACKLIST also needs the renamed one - add to set in helper already has init_service_wrapper
    # Add the mangled name to blacklist via string in helper - already returns false for unknown that we add:
    text = text.replace(
        '"/auto_label",',
        '"/auto_label",\n  "/__blacklisted_init_service_wrapper",',
    )
    print("mangled remaining init_service_wrapper call sites")

PREPROCESS = r'''
router.post("/preprocess", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    const datasetPath = body.datasetPath as string | undefined;
    if (!datasetPath) {
      res.status(400).json({ error: "datasetPath is required" });
      return;
    }
    const resolvedDataset = normalizeTrainingPath(datasetPath, "/app/datasets/my_lora_dataset.json");
    const resolvedOutput = normalizeTrainingPath(body.outputDir, "/app/datasets/preprocessed_tensors");
    const duration = typeof body.maxDuration === "number" ? body.maxDuration : 240.0;
    const container = xpuContainer();
    await mkdir(resolvedOutput, { recursive: true });
    await mkdir("/app/datasets/_tools", { recursive: true });
    const localScript = path.resolve(__aceDirname, "../../scripts/preprocess_dataset.py");
    const sharedScript = "/app/datasets/_tools/preprocess_dataset.py";
    try {
      if (existsSync(localScript)) {
        const fs = await import("fs");
        fs.copyFileSync(localScript, sharedScript);
      }
    } catch (e) {
      console.warn("[Training] stage script", e);
    }
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execFileAsync = promisify(execFile);
    try {
      const { stdout, stderr } = await execFileAsync(
        "docker",
        ["exec", "-w", "/app", container, "python3", sharedScript,
         "--dataset", resolvedDataset, "--output", resolvedOutput,
         "--max-duration", String(duration), "--json"],
        { timeout: 60 * 60 * 1000, maxBuffer: 20 * 1024 * 1024, env: process.env }
      );
      const lines = (stdout || "").trim().split("\n").filter(Boolean);
      const last = lines[lines.length - 1] || "{}";
      try {
        res.json({ status: "Preprocessing complete", ...JSON.parse(last), stderr: (stderr || "").slice(-2000) });
      } catch {
        res.json({ status: "Preprocessing complete", output: (stdout || "").slice(-4000) });
      }
    } catch (err: any) {
      res.status(500).json({ error: "Preprocessing failed on acestep-xpu", detail: String(err?.stderr || err?.message || err) });
    }
  } catch (error) {
    res.status(500).json({ error: error instanceof Error ? error.message : "Preprocessing failed" });
  }
});
'''
text, ok = replace_route(text, "/preprocess", PREPROCESS)
print("preprocess", ok)

training.write_text(text)
print("OK")
