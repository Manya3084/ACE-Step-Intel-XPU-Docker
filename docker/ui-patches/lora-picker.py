#!/usr/bin/env python3
"""LoRA picker — open API + dataset-aware labels under /app/lora_output/<name>/."""
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

/** Label includes dataset folder when path is /app/lora_output/<dataset>/... */
function adapterLabel(adapterPath: string, leafName: string): { label: string; dataset?: string; loss?: number; epoch?: number } {
  const norm = adapterPath.replace(/\\/g, '/');
  const parts = norm.split('/').filter(Boolean);
  const idx = parts.lastIndexOf('lora_output');
  let dataset: string | undefined;
  if (idx >= 0 && parts.length > idx + 1) {
    const next = parts[idx + 1];
    if (next !== 'final' && next !== 'checkpoints' && next !== 'final_lora') {
      dataset = next;
    }
  }
  const mLoss = leafName.match(/loss_([0-9.]+)/);
  const mEp = leafName.match(/epoch_(\d+)/);
  const leaf = leafName === 'final' ? 'final' : leafName;
  const label = dataset
    ? (leaf === 'final' ? `${dataset} / final` : `${dataset} / ${leaf}`)
    : (leaf === 'final' ? 'final (legacy root)' : leaf);
  return {
    label,
    dataset,
    loss: mLoss ? parseFloat(mLoss[1]) : undefined,
    epoch: mEp ? parseInt(mEp[1], 10) : undefined,
  };
}

function walkAdapters(root: string, depth = 0, out: { path: string; label: string; loss?: number; epoch?: number; dataset?: string }[] = []) {
  if (depth > 8) return out;
  try {
    if (!existsSync(root)) return out;
    const adapterChild = path.join(root, 'adapter');
    if (isAdapterDir(adapterChild)) {
      const base = path.basename(root);
      const meta = adapterLabel(adapterChild, base);
      out.push({ path: adapterChild, ...meta });
      return out;
    }
    if (isAdapterDir(root)) {
      const meta = adapterLabel(root, path.basename(root));
      out.push({ path: root, ...meta });
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
    const found: { path: string; label: string; loss?: number; epoch?: number; dataset?: string }[] = [];
    const seen = new Set<string>();
    for (const root of loraRoots()) {
      for (const a of walkAdapters(root)) {
        if (seen.has(a.path)) continue;
        seen.add(a.path);
        found.push(a);
      }
    }
    found.sort((a, b) => {
      const da = a.dataset || '';
      const db = b.dataset || '';
      if (da !== db) return da.localeCompare(db);
      if (a.label.includes('/ final') || a.label.endsWith('final')) return -1;
      if (b.label.includes('/ final') || b.label.endsWith('final')) return 1;
      return (b.epoch ?? -1) - (a.epoch ?? -1);
    });
    res.json({ adapters: found, current: loraState, roots: loraRoots() });
  } catch (error) {
    console.error('[LoRA] List error:', error);
    res.status(500).json({ error: error instanceof Error ? error.message : 'Failed to list LoRAs' });
  }
});
'''

if "function loraRoots" in text:
    text2, n = re.subn(
        r"\nfunction loraRoots\(\): string\[] \{[\s\S]*?router\.get\(['\"]/list['\"][\s\S]*?\}\);\n",
        "\n",
        text,
        count=1,
    )
    text = text2
    print(f"Removed prior walkAdapters/list injection ({n})")

if "router.get('/list'" not in text and 'router.get("/list"' not in text:
    text = text.replace("export default router;", LIST + "\nexport default router;\n")
    print("Added GET /api/lora/list with dataset labels")
else:
    text = re.sub(
        r"router\.get\(\s*['\"]/list['\"]\s*,\s*authMiddleware\s*,",
        "router.get('/list',",
        text,
    )
    if "function walkAdapters" not in text:
        text = text.replace("export default router;", LIST + "\nexport default router;\n")
        print("Appended dataset-aware list helpers")
    else:
        print("list route present; helpers already in file")

if "pre-unload" not in text:
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
print("lora-picker OK — dataset-aware labels")
