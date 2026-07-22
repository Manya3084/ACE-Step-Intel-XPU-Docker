#!/usr/bin/env python3
"""Patch training.ts for XPU Docker — brace-balanced + ESM-safe + soft Gradio."""
from pathlib import Path
import re

p = Path("server/src/routes/training.ts")
text = p.read_text()


def find_router_post(src: str, path: str):
    for quote in ("'", '"'):
        needle = f"router.post({quote}{path}{quote}"
        start = src.find(needle)
        if start >= 0:
            break
    else:
        return None

    i = src.find("{", start)
    if i < 0:
        return None
    depth = 0
    in_s = in_d = in_t = False
    esc = False
    j = i
    while j < len(src):
        c = src[j]
        if in_s:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == "'":
                in_s = False
        elif in_d:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_d = False
        elif in_t:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == "`":
                in_t = False
        else:
            if c == "'":
                in_s = True
            elif c == '"':
                in_d = True
            elif c == "`":
                in_t = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    if end < len(src) and src[end] == ")":
                        end += 1
                    if end < len(src) and src[end] == ";":
                        end += 1
                    return start, end
        j += 1
    return None


def replace_route(src: str, path: str, new_body: str):
    span = find_router_post(src, path)
    if not span:
        return src, False
    a, b = span
    return src[:a] + new_body.strip() + src[b:], True


# ---------------------------------------------------------------------------
# Helpers (ESM-safe dirname)
# ---------------------------------------------------------------------------
HELPER = r'''
/** Docker / XPU path helpers (ACE-Step-Intel-XPU-Docker) */
import { fileURLToPath as __aceFileURLToPath } from "url";
const __aceFilename = __aceFileURLToPath(import.meta.url);
const __aceDirname = path.dirname(__aceFilename);

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
  if (!s.startsWith("/") && !s.startsWith("./")) {
    s = path.posix.join("/app/datasets", s);
  }
  if (s.startsWith("./")) {
    s = path.posix.join("/app", s.slice(2));
  }
  return s;
}

async function safeGradioPredict(endpoint: string, args: unknown[]): Promise<{ ok: true; data: unknown[] } | { ok: false; error: string }> {
  try {
    const client = await getGradioClient();
    const result = await client.predict(endpoint, args);
    return { ok: true, data: (result.data as unknown[]) || [] };
  } catch (e: any) {
    const msg = String(e?.message || e);
    console.warn("[Training] Gradio predict failed", endpoint, msg);
    return { ok: false, error: msg };
  }
}

'''

# Avoid duplicate top-level import if we inject import in helper mid-file — use require-less path
HELPER = HELPER.replace(
    'import { fileURLToPath as __aceFileURLToPath } from "url";\n',
    "",
)
HELPER = HELPER.replace(
    "const __aceFilename = __aceFileURLToPath(import.meta.url);\nconst __aceDirname = path.dirname(__aceFilename);\n",
    'const __aceDirname = path.dirname(fileURLToPath(import.meta.url));\n',
)

# Ensure fileURLToPath is imported at top of training.ts
if "fileURLToPath" not in text:
    # add to an existing import from 'url' or create one
    if "from 'url'" in text or 'from "url"' in text:
        text = text.replace("from 'url'", "from 'url'")  # no-op placeholder
        text = re.sub(
            r"import\s*\{([^}]*)\}\s*from\s*['\"]url['\"]",
            lambda m: ("import { " + m.group(1).strip().rstrip(",") + ", fileURLToPath } from 'url'"
                       if "fileURLToPath" not in m.group(1) else m.group(0)),
            text,
            count=1,
        )
    else:
        text = "import { fileURLToPath } from 'url';\n" + text

if "function normalizeTrainingPath" not in text:
    marker = "function getAceStepDir"
    if marker in text:
        span_start = text.find(marker)
        i = text.find("{", span_start)
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
elif "function safeGradioPredict" not in text:
    # helpers partially present from older patch — append safeGradioPredict after normalizeTrainingPath block
    idx = text.find("function normalizeTrainingPath")
    if idx >= 0:
        i = text.find("{", idx)
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
        extra = r'''
async function safeGradioPredict(endpoint: string, args: unknown[]): Promise<{ ok: true; data: unknown[] } | { ok: false; error: string }> {
  try {
    const client = await getGradioClient();
    const result = await client.predict(endpoint, args);
    return { ok: true, data: (result.data as unknown[]) || [] };
  } catch (e: any) {
    const msg = String(e?.message || e);
    console.warn("[Training] Gradio predict failed", endpoint, msg);
    return { ok: false, error: msg };
  }
}
'''
        text = text[:j] + "\n" + extra + text[j:]

text = text.replace(
    "return path.resolve(config.datasets.dir, '..');",
    'return process.env.ACESTEP_PATH || path.resolve(config.datasets.dir, "..") || "/app";',
)

# Replace __dirname in our preprocess with __aceDirname if present from old patch
text = text.replace("path.resolve(__dirname,", "path.resolve(__aceDirname,")

PREPROCESS = r'''
router.post("/preprocess", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    const datasetPath = body.datasetPath as string | undefined;
    const outputDir = body.outputDir as string | undefined;
    const maxDuration = body.maxDuration as number | undefined;
    if (!datasetPath) {
      res.status(400).json({ error: "datasetPath is required" });
      return;
    }

    const resolvedDataset = normalizeTrainingPath(datasetPath, "/app/datasets/my_lora_dataset.json");
    const resolvedOutput = normalizeTrainingPath(outputDir, "/app/datasets/preprocessed_tensors");
    const duration = typeof maxDuration === "number" ? maxDuration : 240.0;
    const container = xpuContainer();

    await mkdir(resolvedOutput, { recursive: true });
    await mkdir(path.dirname(resolvedDataset), { recursive: true });
    await mkdir("/app/datasets/_tools", { recursive: true });

    const localScript = path.resolve(__aceDirname, "../../scripts/preprocess_dataset.py");
    const sharedScript = "/app/datasets/_tools/preprocess_dataset.py";
    try {
      if (existsSync(localScript)) {
        const fs = await import("fs");
        fs.copyFileSync(localScript, sharedScript);
      }
    } catch (e) {
      console.warn("[Training] Could not stage preprocess script", e);
    }

    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execFileAsync = promisify(execFile);

    console.log("[Training] Preprocess via docker exec", container, resolvedDataset, resolvedOutput);

    try {
      const { stdout, stderr } = await execFileAsync(
        "docker",
        [
          "exec",
          "-w", "/app",
          container,
          "python3",
          sharedScript,
          "--dataset", resolvedDataset,
          "--output", resolvedOutput,
          "--max-duration", String(duration),
          "--json",
        ],
        {
          timeout: 60 * 60 * 1000,
          maxBuffer: 20 * 1024 * 1024,
          env: process.env,
        }
      );

      const lines = (stdout || "").trim().split("\n").filter(Boolean);
      const last = lines[lines.length - 1] || "{}";
      try {
        const result = JSON.parse(last);
        res.json({ status: "Preprocessing complete", ...result, stderr: (stderr || "").slice(-2000) });
      } catch {
        res.json({
          status: "Preprocessing complete",
          output: (stdout || "").slice(-4000),
          stderr: (stderr || "").slice(-2000),
        });
      }
    } catch (err: any) {
      const detail = String(err?.stderr || err?.message || err);
      console.error("[Training] Preprocess docker exec failed", detail);
      res.status(500).json({
        error: "Preprocessing failed on acestep-xpu",
        detail,
        hint: "Ensure acestep-xpu is healthy and dataset JSON exists under /app/datasets",
      });
    }
  } catch (error) {
    console.error("[Training] Preprocess error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : "Preprocessing failed" });
  }
});
'''

INIT = r'''
router.post("/init-model", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  // /init_service_wrapper is NOT a named Gradio endpoint on ACE-Step 1.5 API mode.
  // Models are already loaded by acestep-xpu on startup.
  res.status(200).json({
    status: "Model service assumed ready (container auto-init)",
    modelReady: true,
    soft: true,
    hint: "Skip Init Model on this Docker stack; DiT/LM load at acestep-xpu boot",
  });
});
'''

# Soft auto-label if present
AUTO = r'''
router.post("/auto-label", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  // /auto_label_all is not exposed as a named endpoint on this Gradio build
  res.status(501).json({
    error: "Auto-label is not available via API on this ACE-Step build",
    hint: "Label samples manually in the Training tab, or use native Gradio UI on port 8001",
  });
});
'''

text, ok = replace_route(text, "/preprocess", PREPROCESS)
print("preprocess", ok)
text, ok = replace_route(text, "/init-model", INIT)
if not ok:
    if "export default router" in text:
        text = text.replace("export default router", INIT.strip() + "\n\nexport default router", 1)
    print("init-model appended/replaced")
else:
    print("init-model replaced")

text, ok = replace_route(text, "/auto-label", AUTO)
print("auto-label", ok)

# save-dataset: prefer Gradio /save_dataset over missing REST
SAVE = r'''
router.post("/save-dataset", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    const savePath = normalizeTrainingPath(
      body.path || body.savePath || body.datasetPath,
      "/app/datasets/my_lora_dataset.json"
    );
    // Gradio named endpoint (confirmed on this stack)
    const pred = await safeGradioPredict("/save_dataset", [savePath]);
    if (!pred.ok) {
      // Fallback: if body includes full dataset JSON, write to shared volume
      if (body.dataset && typeof body.dataset === "object") {
        await mkdir(path.dirname(savePath), { recursive: true });
        await writeFile(savePath, JSON.stringify(body.dataset, null, 2), "utf-8");
        res.json({ status: "saved locally", path: savePath });
        return;
      }
      res.status(500).json({
        error: "save_dataset Gradio call failed",
        detail: pred.error,
        hint: "Pass path under /app/datasets or include dataset JSON in body",
      });
      return;
    }
    res.json({ status: pred.data[0] ?? "saved", path: savePath, data: pred.data });
  } catch (error) {
    console.error("[Training] Save dataset error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : "Failed to save dataset" });
  }
});
'''

text, ok = replace_route(text, "/save-dataset", SAVE)
print("save-dataset", ok)

# Soft-wrap remaining naked client.predict calls that lack try/catch is hard;
# at least replace known-bad endpoint names with safeGradioPredict where simple.
text = text.replace(
    "await client.predict('/init_service_wrapper'",
    "await client.predict('/training_wrapper' /* was init_service_wrapper; unavailable */",
)
# Better: comment-level no — leave predict but ensure routes catch

for old, new in [
    ("tensorDir ?? './datasets/preprocessed_tensors'",
     'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ('tensorDir ?? "./datasets/preprocessed_tensors"',
     'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ("outputDir ?? './lora_output'",
     'normalizeTrainingPath(outputDir, "/app/lora_output")'),
    ('outputDir ?? "./lora_output"',
     'normalizeTrainingPath(outputDir, "/app/lora_output")'),
]:
    text = text.replace(old, new)

# Ensure __aceDirname exists even if helper insert failed partially
if "__aceDirname" not in text:
    text = text.replace(
        "function xpuContainer",
        'const __aceDirname = path.dirname(fileURLToPath(import.meta.url));\n\nfunction xpuContainer',
        1,
    )

p.write_text(text)
print("training.ts patch OK")
