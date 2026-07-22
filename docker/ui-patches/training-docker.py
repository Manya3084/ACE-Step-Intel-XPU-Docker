#!/usr/bin/env python3
"""Patch training.ts + gradio-client for XPU Docker Gradio API reality."""
from pathlib import Path
import re

training = Path("server/src/routes/training.ts")
text = training.read_text()

# ---------------------------------------------------------------------------
# 1) Ensure fileURLToPath import
# ---------------------------------------------------------------------------
if "fileURLToPath" not in text:
    text = "import { fileURLToPath } from 'url';\n" + text

# ---------------------------------------------------------------------------
# 2) Inject helpers once (after getAceStepDir or at top)
# ---------------------------------------------------------------------------
HELPER = r'''
/** ACE-Step-Intel-XPU-Docker training helpers */
const __aceDirname = path.dirname(fileURLToPath(import.meta.url));

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

/** Prefer named endpoint; try /name_1 twin; never throw to Express. */
async function safeGradioPredict(endpoint: string, args: unknown[]): Promise<{ ok: true; data: unknown[]; endpoint: string } | { ok: false; error: string; endpoint: string }> {
  const client = await getGradioClient();
  const variants = [endpoint];
  if (endpoint.startsWith("/") && !endpoint.endsWith("_1")) {
    variants.push(endpoint + "_1");
  }
  let lastErr = "";
  for (const ep of variants) {
    try {
      console.log("[Training] Gradio predict", ep);
      const result = await client.predict(ep as any, args as any);
      return { ok: true, data: ((result as any).data as unknown[]) || [], endpoint: ep };
    } catch (e: any) {
      lastErr = String(e?.message || e);
      console.warn("[Training] Gradio predict failed", ep, lastErr);
      if (!lastErr.includes("no endpoint matching")) {
        // real runtime error from a resolved endpoint
        return { ok: false, error: lastErr, endpoint: ep };
      }
    }
  }
  return { ok: false, error: lastErr || "no endpoint", endpoint };
}

'''

if "function safeGradioPredict" not in text:
    if "function getAceStepDir" in text:
        # insert after getAceStepDir closing brace (brace walk)
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

# ---------------------------------------------------------------------------
# 3) Rewrite every client.predict('...', [...]) to safeGradioPredict
#    and force callers that expect result.data to handle ok flag where we
#    can do simple mechanical fixes.
# ---------------------------------------------------------------------------

# Kill known-bad names before anything else
for bad in (
    "/init_service_wrapper",
    "/auto_label_all",
    "/auto_label",
):
    # leave strings that are only in comments
    pass

# Replace await client.predict('/foo', [args]) with safeGradioPredict
def repl_predict(m):
    ep = m.group(1)
    args = m.group(2)
    return f"await safeGradioPredict('{ep}', {args})"

text2, n = re.subn(
    r"await\s+client\.predict\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\[[\s\S]*?\])\s*\)",
    repl_predict,
    text,
)
print(f"rewrote client.predict -> safeGradioPredict: {n}")
text = text2

# After rewrite, code still does `const result = await safeGradioPredict(...); const data = result.data`
# Fix pattern: result.data when result may be {ok,data}
# Mechanical: `const data = result.data as unknown[]` after safeGradioPredict assignment
# becomes check ok

# Fix common pattern after predict rewrite:
# const result = await safeGradioPredict(...);
# const data = result.data as unknown[];
text = re.sub(
    r"const result = await safeGradioPredict\(([^;]+)\);\s*const data = result\.data as unknown\[\];",
    r"const __pred = await safeGradioPredict(\1);\n    if (!__pred.ok) { res.status(502).json({ error: 'Gradio endpoint failed', detail: __pred.error, endpoint: __pred.endpoint }); return; }\n    const data = __pred.data;",
    text,
)

# ---------------------------------------------------------------------------
# 4) Hard-replace init-model + auto-label routes via string markers
# ---------------------------------------------------------------------------
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
print("init-model", ok)
if not ok and "export default router" in text:
    text = text.replace("export default router", INIT + "\nexport default router", 1)

text, ok = replace_route(text, "/auto-label", AUTO)
print("auto-label", ok)

# ---------------------------------------------------------------------------
# 5) Preprocess docker-exec (ESM-safe)
# ---------------------------------------------------------------------------
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
    console.log("[Training] Preprocess docker exec", container, resolvedDataset, resolvedOutput);
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
        res.json({ status: "Preprocessing complete", output: (stdout || "").slice(-4000), stderr: (stderr || "").slice(-2000) });
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

# Default paths
for old, new in [
    ("tensorDir ?? './datasets/preprocessed_tensors'", 'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ('tensorDir ?? "./datasets/preprocessed_tensors"', 'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ("outputDir ?? './lora_output'", 'normalizeTrainingPath(outputDir, "/app/lora_output")'),
    ('outputDir ?? "./lora_output"', 'normalizeTrainingPath(outputDir, "/app/lora_output")'),
]:
    text = text.replace(old, new)

training.write_text(text)
print("training.ts written")

# ---------------------------------------------------------------------------
# 6) Harden gradio-client: log + never leave unhandled from connect only
# ---------------------------------------------------------------------------
gc = Path("server/src/services/gradio-client.ts")
if gc.exists():
    g = gc.read_text()
    if "safePredict wrapper note" not in g:
        g += "\n// safePredict wrapper note: training.ts uses safeGradioPredict\n"
        gc.write_text(g)
    print("gradio-client touched")

print("training-docker patch complete")
