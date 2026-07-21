#!/usr/bin/env python3
"""Patch ace-step-ui training.ts for Intel XPU Docker split (UI + acestep-xpu)."""
from pathlib import Path
import re

p = Path("server/src/routes/training.ts")
text = p.read_text()

# --- Helper block injected after imports ---
HELPER = r'''
/** Docker / XPU path helpers (ACE-Step-Intel-XPU-Docker) */
function xpuContainer(): string {
  return process.env.XPU_CONTAINER_NAME || 'acestep-xpu';
}

function normalizeTrainingPath(input: string | undefined | null, fallback: string): string {
  let s = (input && String(input).trim()) || fallback;
  // Rewrite single-machine defaults to shared Docker mounts
  s = s.replace(/\/app\/ACE-Step-1\.5\/datasets/g, '/app/datasets');
  s = s.replace(/ACE-Step-1\.5\/datasets/g, '/app/datasets');
  if (s === './datasets' || s === 'datasets') s = '/app/datasets';
  if (s === './datasets/preprocessed_tensors' || s.endsWith('datasets/preprocessed_tensors')) {
    s = '/app/datasets/preprocessed_tensors';
  }
  if (s === './lora_output' || s === 'lora_output') s = '/app/lora_output';
  if (!s.startsWith('/') && !s.startsWith('./')) {
    // bare relative -> under shared datasets
    s = path.posix.join('/app/datasets', s);
  }
  if (s.startsWith('./')) {
    s = path.posix.join('/app', s.slice(2));
  }
  return s;
}
'''

if "function normalizeTrainingPath" not in text:
    # Insert after getAceStepDir function if present, else after imports
    if "function getAceStepDir" in text:
        text = re.sub(
            r"(function getAceStepDir\(\): string \{[\s\S]*?\n\})",
            r"\1\n" + HELPER,
            text,
            count=1,
        )
    else:
        text = HELPER + "\n" + text

# Force getAceStepDir to prefer /app when ACESTEP_PATH set (already does) — also default to /app
text = text.replace(
    "return path.resolve(config.datasets.dir, '..');",
    "return process.env.ACESTEP_PATH || path.resolve(config.datasets.dir, '..') || '/app';",
)

# --- Replace preprocess route body to docker-exec into XPU ---
PREPROCESS_NEW = r'''
router.post('/preprocess', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const { datasetPath, outputDir, maxDuration } = req.body || {};
    if (!datasetPath) {
      res.status(400).json({ error: 'datasetPath is required' });
      return;
    }

    const resolvedDataset = normalizeTrainingPath(datasetPath, '/app/datasets/my_lora_dataset.json');
    const resolvedOutput = normalizeTrainingPath(
      outputDir,
      '/app/datasets/preprocessed_tensors'
    );
    const duration = typeof maxDuration === 'number' ? maxDuration : 240.0;
    const container = xpuContainer();

    // Ensure dirs exist on shared volume (UI side)
    await mkdir(resolvedOutput, { recursive: true });
    await mkdir(path.dirname(resolvedDataset), { recursive: true });

    // Copy UI preprocess script onto shared volume so XPU can run it
    const localScript = path.resolve(__dirname, '../../scripts/preprocess_dataset.py');
    const sharedScript = '/app/datasets/_tools/preprocess_dataset.py';
    try {
      await mkdir('/app/datasets/_tools', { recursive: true });
      if (existsSync(localScript)) {
        const { copyFileSync } = await import('fs');
        copyFileSync(localScript, sharedScript);
      }
    } catch (e) {
      console.warn('[Training] Could not stage preprocess script on shared volume', e);
    }

    const { execFile } = await import('child_process');
    const { promisify } = await import('util');
    const execFileAsync = promisify(execFile);

    const scriptInXpu = existsSync(sharedScript)
      ? sharedScript
      : '/app/datasets/_tools/preprocess_dataset.py';

    console.log('[Training] Preprocess via docker exec', container, resolvedDataset, '->', resolvedOutput);

    try {
      const { stdout, stderr } = await execFileAsync(
        'docker',
        [
          'exec',
          '-w', '/app',
          container,
          'python3', scriptInXpu,
          '--dataset', resolvedDataset,
          '--output', resolvedOutput,
          '--max-duration', String(duration),
          '--json',
        ],
        {
          timeout: 60 * 60 * 1000, // 1h
          maxBuffer: 20 * 1024 * 1024,
          env: process.env,
        }
      );

      const lines = (stdout || '').trim().split('\n').filter(Boolean);
      const last = lines[lines.length - 1] || '{}';
      try {
        const result = JSON.parse(last);
        res.json({ status: 'Preprocessing complete', ...result, stderr: (stderr || '').slice(-2000) });
      } catch {
        res.json({
          status: 'Preprocessing complete',
          output: (stdout || '').slice(-4000),
          stderr: (stderr || '').slice(-2000),
        });
      }
    } catch (err: any) {
      const detail = String(err?.stderr || err?.message || err);
      console.error('[Training] Preprocess docker exec failed', detail);
      res.status(500).json({
        error: 'Preprocessing failed on acestep-xpu',
        detail,
        hint: 'Ensure acestep-xpu is healthy, dataset JSON exists under /app/datasets, and models are initialized. First preprocess loads VAE and can take a long time on Arc.',
      });
    }
  } catch (error) {
    console.error('[Training] Preprocess error:', error);
    res.status(500).json({ error: error instanceof Error ? error.message : 'Preprocessing failed' });
  }
});
'''

# Replace existing preprocess handler
text2, n = re.subn(
    r"router\.post\('/preprocess',\s*authMiddleware,\s*async \(req: AuthenticatedRequest, res: Response\) => \{[\s\S]*?\n\}\);",
    PREPROCESS_NEW.strip(),
    text,
    count=1,
)
if n == 0:
    raise SystemExit('Could not find /preprocess route to replace')
text = text2
print('Patched /preprocess -> docker exec on XPU')

# --- Harden init-model: never throw unhandled; prefer 501 over crash ---
INIT_NEW = r'''
router.post('/init-model', authMiddleware, async (req: AuthenticatedRequest, res: Response) => {
  try {
    const body = req.body || {};
    const {
      checkpoint,
      configPath,
      device = 'xpu',
      initLlm = false,
      lmModelPath = '',
      backend = 'pt',
      useFlashAttention = false,
      offloadToCpu = true,
      offloadDitToCpu = false,
      compileModel = false,
      quantization = false,
    } = body;

    // On this Docker stack models are usually already loaded at acestep-xpu boot.
    // Still try Gradio; on any failure return a soft status so the UI process stays up.
    try {
      const client = await getGradioClient();
      const result = await client.predict('/init_service_wrapper', [
        checkpoint ?? '',
        configPath ?? process.env.ACESTEP_CONFIG_PATH ?? 'acestep-v15-turbo',
        device,
        initLlm,
        lmModelPath,
        backend,
        useFlashAttention,
        offloadToCpu,
        offloadDitToCpu,
        compileModel,
        quantization,
      ]);
      const data = (result.data as unknown[]) || [];
      res.json({
        status: data[0] ?? 'ok',
        modelReady: data[1] !== false,
        note: 'init_service_wrapper completed',
      });
    } catch (gradioError: any) {
      console.warn('[Training] init-model Gradio call failed (non-fatal):', gradioError?.message || gradioError);
      res.status(200).json({
        status: 'Model service assumed ready (container auto-init). Gradio init endpoint unavailable or failed.',
        modelReady: true,
        soft: true,
        detail: String(gradioError?.message || gradioError),
        hint: 'acestep-xpu already loads DiT/LM on startup. Continue with dataset / train steps. Use Restart acestep-xpu if the GPU state is bad.',
      });
    }
  } catch (error) {
    console.error('[Training] Init model error:', error);
    res.status(200).json({
      status: 'Init skipped',
      modelReady: true,
      soft: true,
      error: error instanceof Error ? error.message : 'Model init failed',
    });
  }
});
'''

text3, n2 = re.subn(
    r"router\.post\('/init-model',\s*authMiddleware,\s*async \(req: AuthenticatedRequest, res: Response\) => \{[\s\S]*?\n\}\);",
    INIT_NEW.strip(),
    text,
    count=1,
)
if n2 == 0:
    print('WARN: init-model route not replaced')
else:
    text = text3
    print('Patched /init-model soft-fail')

# --- Default tensor/output paths in start + load-tensors ---
text = text.replace(
    "tensorDir ?? './datasets/preprocessed_tensors'",
    "normalizeTrainingPath(tensorDir, '/app/datasets/preprocessed_tensors')",
)
text = text.replace(
    "outputDir ?? './lora_output'",
    "normalizeTrainingPath(outputDir, '/app/lora_output')",
)
text = text.replace(
    "tensorDir ?? './datasets/preprocessed_tensors'",
    "normalizeTrainingPath(tensorDir, '/app/datasets/preprocessed_tensors')",
)

# load-tensors single arg form
text = re.sub(
    r"client\.predict\('/load_training_dataset',\s*\[\s*tensorDir \?\? '[^']+'\s*\]\)",
    "client.predict('/load_training_dataset', [normalizeTrainingPath(tensorDir, '/app/datasets/preprocessed_tensors')])",
    text,
)

# lora-checkpoints default
text = text.replace(
    "(req.query.dir as string) || './lora_output'",
    "normalizeTrainingPath((req.query.dir as string) || '', '/app/lora_output')",
)

p.write_text(text)
print('training.ts Docker training patch complete')
