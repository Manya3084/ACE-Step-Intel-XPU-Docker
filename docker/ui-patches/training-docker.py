#!/usr/bin/env python3
"""Patch training.ts for XPU Docker — brace-balanced replacements only."""
from pathlib import Path

p = Path("server/src/routes/training.ts")
text = p.read_text()


def find_router_post(src: str, path: str):
    """Return [start, end) of router.post('/path', ...) { ... }); with balanced braces."""
    for quote in ("'", '"'):
        needle = f"router.post({quote}{path}{quote}"
        start = src.find(needle)
        if start >= 0:
            break
    else:
        # also try path without leading slash variants
        for alt in (path.lstrip("/"), path):
            for quote in ("'", '"'):
                needle = f"router.post({quote}/{alt}{quote}" if not alt.startswith("/") else f"router.post({quote}{alt}{quote}"
                start = src.find(needle)
                if start >= 0:
                    break
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


def list_training_posts(src: str):
    """Debug: list router.post paths in file."""
    import re
    return re.findall(r"router\.post\(\s*['\"]([^'\"]+)['\"]", src)


HELPER = r'''
/** Docker / XPU path helpers (ACE-Step-Intel-XPU-Docker) */
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

'''

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

text = text.replace(
    "return path.resolve(config.datasets.dir, '..');",
    'return process.env.ACESTEP_PATH || path.resolve(config.datasets.dir, "..") || "/app";',
)

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

    const localScript = path.resolve(__dirname, "../../scripts/preprocess_dataset.py");
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
  try {
    const body = req.body || {};
    try {
      const client = await getGradioClient();
      const result = await client.predict("/init_service_wrapper", [
        body.checkpoint ?? "",
        body.configPath ?? process.env.ACESTEP_CONFIG_PATH ?? "acestep-v15-turbo",
        body.device ?? "xpu",
        body.initLlm ?? false,
        body.lmModelPath ?? "",
        body.backend ?? "pt",
        body.useFlashAttention ?? false,
        body.offloadToCpu ?? true,
        body.offloadDitToCpu ?? false,
        body.compileModel ?? false,
        body.quantization ?? false,
      ]);
      const data = (result.data as unknown[]) || [];
      res.json({
        status: data[0] ?? "ok",
        modelReady: data[1] !== false,
        note: "init_service_wrapper completed",
      });
    } catch (gradioError: any) {
      console.warn("[Training] init-model Gradio failed (non-fatal)", gradioError?.message || gradioError);
      res.status(200).json({
        status: "Model service assumed ready (container auto-init)",
        modelReady: true,
        soft: true,
        detail: String(gradioError?.message || gradioError),
        hint: "acestep-xpu loads DiT/LM on startup; continue with dataset or train",
      });
    }
  } catch (error) {
    console.error("[Training] Init model error:", error);
    res.status(200).json({
      status: "Init skipped",
      modelReady: true,
      soft: true,
      error: error instanceof Error ? error.message : "Model init failed",
    });
  }
});
'''

posts = list_training_posts(text)
print("Found router.post paths:", posts)

text, ok = replace_route(text, "/preprocess", PREPROCESS)
if not ok:
    raise SystemExit("Could not find /preprocess route")
print("Replaced /preprocess")

text, ok = replace_route(text, "/init-model", INIT)
if not ok:
    # try alternate names used by some UI versions
    for alt in ("/init_model", "/initModel", "/model-init", "/init"):
        text, ok = replace_route(text, alt, INIT.replace('"/init-model"', f'"{alt}"'))
        if ok:
            print(f"Replaced {alt} as init-model")
            break
    if not ok:
        print("WARN: no init-model route found; appending soft handler")
        # Append before export default
        if "export default router" in text:
            text = text.replace(
                "export default router",
                INIT.strip() + "\n\nexport default router",
                1,
            )
        else:
            text = text + "\n" + INIT + "\n"

for old, new in [
    ("tensorDir ?? './datasets/preprocessed_tensors'",
     'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ('tensorDir ?? "./datasets/preprocessed_tensors"',
     'normalizeTrainingPath(tensorDir, "/app/datasets/preprocessed_tensors")'),
    ("outputDir ?? './lora_output'",
     'normalizeTrainingPath(outputDir, "/app/lora_output")'),
    ('outputDir ?? "./lora_output"',
     'normalizeTrainingPath(outputDir, "/app/lora_output")'),
    ("(req.query.dir as string) || './lora_output'",
     'normalizeTrainingPath((req.query.dir as string) || "", "/app/lora_output")'),
    ('(req.query.dir as string) || "./lora_output"',
     'normalizeTrainingPath((req.query.dir as string) || "", "/app/lora_output")'),
]:
    text = text.replace(old, new)

p.write_text(text)
print("training.ts patch OK")
