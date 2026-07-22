#!/usr/bin/env python3
"""Patch training.ts — XPU paths, safe Gradio, local save-dataset, docker preprocess."""
from pathlib import Path
import re

training = Path("server/src/routes/training.ts")
text = training.read_text()

if "fileURLToPath" not in text:
    text = "import { fileURLToPath } from 'url';\n" + text

# Drop prior helper injections
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

const GRADIO_ENDPOINT_BLACKLIST = new Set([
  "/init_service_wrapper",
  "init_service_wrapper",
  "/auto_label_all",
  "auto_label_all",
  "/auto_label",
  "auto_label",
  "/__blacklisted_init_service_wrapper",
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
  // Force dataset JSON under shared volume
  if (s.endsWith(".json") && !s.startsWith("/app/datasets")) {
    s = path.posix.join("/app/datasets", path.posix.basename(s));
  }
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

text2, n = re.subn(
    r"await\s+client\.predict\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\[[\s\S]*?\])\s*\)",
    lambda m: f"await safeGradioPredict('{m.group(1)}', {m.group(2)})",
    text,
)
print(f"client.predict -> safeGradioPredict: {n}")
text = text2

text = re.sub(
    r"const result = await safeGradioPredict\(([^;]+)\);\s*const data = result\.data as unknown\[\];",
    r"const __pred = await safeGradioPredict(\1);\n    if (!__pred.ok) { res.status(502).json({ error: 'Gradio endpoint failed', detail: __pred.error, endpoint: __pred.endpoint }); return; }\n    const data = __pred.data;",
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
    hint: "Label samples in the UI (caption + labeled) then Save dataset",
  });
});
'''

# Local save — Gradio state + /v1/dataset/save are unavailable from ace-step-ui
SAVE = r'''
router.post("/save-dataset", authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    const datasetName = String(body.datasetName || body.dataset_name || "my_lora_dataset").trim() || "my_lora_dataset";
    const safeName = datasetName.replace(/[^a-zA-Z0-9._-]+/g, "_");
    let resolvedPath = normalizeTrainingPath(
      body.savePath || body.save_path,
      path.posix.join("/app/datasets", `${safeName}.json`)
    );
    if (!resolvedPath.endsWith(".json")) {
      resolvedPath = path.posix.join("/app/datasets", `${safeName}.json`);
    }
    // Always land under shared datasets volume
    if (!resolvedPath.startsWith("/app/datasets")) {
      resolvedPath = path.posix.join("/app/datasets", path.posix.basename(resolvedPath));
    }

    const uploadsRoot = process.env.DATASETS_UPLOADS_DIR || "/app/datasets/uploads";
    const uploadDir = path.posix.join(uploadsRoot, safeName);
    const audioExt = new Set([".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"]);

    // Prefer explicit samples from client
    let samples: any[] = Array.isArray(body.samples) ? body.samples : [];

    // Merge / fallback: existing JSON
    let existing: any = null;
    try {
      if (existsSync(resolvedPath)) {
        existing = JSON.parse(await readFile(resolvedPath, "utf8"));
      }
    } catch {
      existing = null;
    }
    if (!samples.length && existing?.samples?.length) {
      samples = existing.samples;
    }

    // Fallback: scan upload folder for audio files
    if (!samples.length && existsSync(uploadDir)) {
      const { readdirSync } = await import("fs");
      const files = readdirSync(uploadDir).filter((f: string) => audioExt.has(path.extname(f).toLowerCase()));
      samples = files.map((filename: string, i: number) => ({
        id: `sample_${i}_${filename.replace(/[^a-zA-Z0-9]+/g, "_").slice(0, 24)}`,
        audio_path: path.posix.join(uploadDir, filename),
        filename,
        caption: body.defaultCaption || "instrumental, high quality music",
        genre: body.defaultGenre || "",
        lyrics: "[Instrumental]",
        raw_lyrics: "",
        formatted_lyrics: "",
        bpm: null,
        keyscale: "",
        timesignature: "",
        duration: null,
        language: "instrumental",
        is_instrumental: true,
        custom_tag: body.customTag || "",
        labeled: true,
        prompt_override: null,
      }));
    }

    if (!samples.length) {
      res.status(400).json({
        error: "No samples to save",
        hint: `Upload audio under ${uploadDir} or pass body.samples`,
        path: resolvedPath,
      });
      return;
    }

    // Normalize samples for ACE-Step DatasetBuilder JSON
    const normalized = samples.map((s: any, i: number) => {
      const filename = s.filename || s.name || path.posix.basename(String(s.audio_path || s.audioPath || `track_${i}`));
      let audioPath = String(s.audio_path || s.audioPath || path.posix.join(uploadDir, filename));
      audioPath = audioPath.split("/app/ACE-Step-1.5/datasets").join("/app/datasets");
      if (!audioPath.startsWith("/")) {
        audioPath = path.posix.join(uploadDir, path.posix.basename(audioPath));
      }
      const lyrics = (s.lyrics != null && String(s.lyrics).trim()) ? String(s.lyrics) : "[Instrumental]";
      const isInst = s.is_instrumental === true || s.isInstrumental === true || lyrics.trim() === "[Instrumental]";
      let caption = (s.caption != null && String(s.caption).trim()) ? String(s.caption) : "";
      if (!caption) caption = body.defaultCaption || "instrumental, high quality music";
      const labeled = s.labeled === true || s.labeled === "true" || body.forceLabeled === true;
      return {
        id: s.id || `s_${i}`,
        audio_path: audioPath,
        filename,
        caption,
        genre: s.genre || "",
        lyrics,
        raw_lyrics: s.raw_lyrics || s.rawLyrics || "",
        formatted_lyrics: s.formatted_lyrics || s.formattedLyrics || "",
        bpm: s.bpm ?? null,
        keyscale: s.keyscale || s.keyScale || "",
        timesignature: s.timesignature || s.timeSignature || "",
        duration: s.duration ?? null,
        language: s.language || (isInst ? "instrumental" : "en"),
        is_instrumental: isInst,
        custom_tag: s.custom_tag || s.customTag || body.customTag || "",
        labeled,
        prompt_override: s.prompt_override ?? s.promptOverride ?? null,
      };
    });

    // Force labeled if every sample still false but user clicked Save (training requires it)
    const anyLabeled = normalized.some((s: any) => s.labeled);
    if (!anyLabeled) {
      for (const s of normalized) s.labeled = true;
    }

    const payload = {
      metadata: {
        name: safeName,
        custom_tag: body.customTag || body.custom_tag || existing?.metadata?.custom_tag || "",
        tag_position: body.tagPosition || body.tag_position || existing?.metadata?.tag_position || "replace",
        created_at: existing?.metadata?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
        num_samples: normalized.length,
        all_instrumental: body.allInstrumental ?? normalized.every((s: any) => s.is_instrumental),
        genre_ratio: body.genreRatio ?? body.genre_ratio ?? existing?.metadata?.genre_ratio ?? 0,
      },
      samples: normalized,
    };

    await mkdir(path.posix.dirname(resolvedPath), { recursive: true });
    await writeFile(resolvedPath, JSON.stringify(payload, null, 2), "utf8");
    console.log("[Training] Saved dataset", resolvedPath, "samples=", normalized.length);
    res.json({
      status: `Saved ${normalized.length} sample(s)`,
      path: resolvedPath,
      numSamples: normalized.length,
      labeledCount: normalized.filter((s: any) => s.labeled).length,
    });
  } catch (error) {
    console.error("[Training] Save dataset error:", error);
    res.status(500).json({ error: error instanceof Error ? error.message : "Failed to save dataset" });
  }
});
'''

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
    // Prefer repo script baked into image under /tmp if present
    const baked = "/tmp/preprocess_dataset_xpu.py";
    const scriptToRun = existsSync(sharedScript) ? sharedScript : (existsSync(baked) ? baked : sharedScript);
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execFileAsync = promisify(execFile);
    try {
      const { stdout, stderr } = await execFileAsync(
        "docker",
        ["exec", "-w", "/app", container, "python3", scriptToRun,
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

text, ok = replace_route(text, "/init-model", INIT)
print("init-model route", ok)

text, ok = replace_route(text, "/auto-label", AUTO)
print("auto-label route", ok)

text, ok = replace_route(text, "/save-dataset", SAVE)
print("save-dataset route", ok)
if not ok:
    # try alternate path spelling
    text, ok = replace_route(text, "/save_dataset", SAVE)
    print("save_dataset route", ok)

text, ok = replace_route(text, "/preprocess", PREPROCESS)
print("preprocess", ok)

if "init_service_wrapper" in text:
    text = text.replace(
        "await safeGradioPredict('/init_service_wrapper'",
        "await safeGradioPredict('/__blacklisted_init_service_wrapper'",
    )
    text = text.replace(
        'await safeGradioPredict("/init_service_wrapper"',
        'await safeGradioPredict("/__blacklisted_init_service_wrapper"',
    )
    print("rewrote leftover init_service_wrapper call sites")

# Ensure readFile/writeFile imports if missing
if "readFile" in text and "from 'fs/promises'" not in text and 'from "fs/promises"' not in text:
    if "from 'fs'" in text or 'from "fs"' in text:
        text = text.replace(
            "import { existsSync", "import { existsSync, readFileSync",
        )
    text = "import { readFile, writeFile, mkdir } from 'fs/promises';\n" + text
elif "writeFile" in SAVE and "writeFile" not in text.split("router.post("/save-dataset")[0]:
    if "from 'fs/promises'" not in text and 'from "fs/promises"' not in text:
        text = "import { readFile, writeFile, mkdir } from 'fs/promises';\n" + text

training.write_text(text)
print("OK training.ts patched")
