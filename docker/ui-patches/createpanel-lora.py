#!/usr/bin/env python3
"""Patch components/CreatePanel.tsx — adapter picker inside native LoRA section.

Adds:
- state for discovered adapters from GET /api/lora/list (no JWT)
- <select> above the path field when LoRA panel is open
- load/unload without requiring token (OPEN_LOCAL_AUTH)
"""
from pathlib import Path
import re
import sys

p = Path("components/CreatePanel.tsx")
if not p.is_file():
    # sometimes under src/
    for c in Path(".").rglob("CreatePanel.tsx"):
        p = c
        break
if not p.is_file():
    print("CreatePanel.tsx not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
if "ace-lora-adapter-select" in text or "fetchLoraAdapters" in text:
    print("CreatePanel already patched")
    sys.exit(0)

# 1) Extra state after lora loading state
old_state = "  const [isLoraLoading, setIsLoraLoading] = useState(false);"
new_state = """  const [isLoraLoading, setIsLoraLoading] = useState(false);
  const [loraAdapters, setLoraAdapters] = useState<{ path: string; label: string; loss?: number; epoch?: number }[]>([]);
  const [loraListStatus, setLoraListStatus] = useState<string>('');"""
if old_state not in text:
    print("WARN: isLoraLoading state not found", file=sys.stderr)
else:
    text = text.replace(old_state, new_state, 1)
    print("Added loraAdapters state")

# 2) Fetch list helper + effect near LoRA handlers
marker = "  // LoRA API handlers"
fetch_block = r'''
  // ACE-Step-Intel-XPU-Docker: list trained adapters (open API)
  const fetchLoraAdapters = useCallback(async () => {
    setLoraListStatus('Listing…');
    try {
      const res = await fetch('/api/lora/list');
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const adapters = Array.isArray(data.adapters) ? data.adapters : [];
      setLoraAdapters(adapters);
      setLoraListStatus(adapters.length ? `${adapters.length} adapter(s)` : 'No adapters under /app/lora_output');
      if (adapters.length && !loraPath) {
        setLoraPath(adapters[0].path);
      }
    } catch (e) {
      setLoraListStatus(e instanceof Error ? e.message : 'List failed');
    }
  }, [loraPath]);

  useEffect(() => {
    if (showLoraPanel) void fetchLoraAdapters();
  }, [showLoraPanel, fetchLoraAdapters]);

  // LoRA API handlers'''

if marker in text:
    text = text.replace(marker, fetch_block, 1)
    print("Added fetchLoraAdapters")
else:
    print("WARN: LoRA API handlers marker missing", file=sys.stderr)

# 3) Soften token checks on LoRA handlers (OPEN_LOCAL_AUTH)
text = text.replace(
    """  const handleLoraToggle = async () => {
    if (!token) {
      setLoraError('Please sign in to use LoRA');
      return;
    }
    if (!loraPath.trim()) {
      setLoraError('Please enter a LoRA path');
      return;
    }

    setIsLoraLoading(true);
    setLoraError(null);

    try {
      if (loraLoaded) {
        await handleLoraUnload();
      } else {
        const result = await generateApi.loadLora({ lora_path: loraPath }, token);
        setLoraLoaded(true);
        console.log('LoRA loaded:', result?.message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'LoRA operation failed';
      setLoraError(message);
      console.error('LoRA error:', err);
    } finally {
      setIsLoraLoading(false);
    }
  };""",
    """  const handleLoraToggle = async () => {
    if (!loraPath.trim()) {
      setLoraError('Please enter or pick a LoRA path');
      return;
    }

    setIsLoraLoading(true);
    setLoraError(null);

    try {
      if (loraLoaded) {
        await handleLoraUnload();
      } else {
        // token optional under OPEN_LOCAL_AUTH — still pass if present
        const result = await generateApi.loadLora({ lora_path: loraPath }, token || '');
        setLoraLoaded(true);
        console.log('LoRA loaded:', result?.message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'LoRA operation failed';
      setLoraError(message);
      console.error('LoRA error:', err);
    } finally {
      setIsLoraLoading(false);
    }
  };""",
)

text = text.replace(
    """  const handleLoraUnload = async () => {
    if (!token) return;
    
    setIsLoraLoading(true);
    setLoraError(null);

    try {
      const result = await generateApi.unloadLora(token);
""",
    """  const handleLoraUnload = async () => {
    setIsLoraLoading(true);
    setLoraError(null);

    try {
      const result = await generateApi.unloadLora(token || '');
""",
)

text = text.replace(
    "    if (!token || !loraLoaded) return;\n\n    try {\n      await generateApi.setLoraScale({ scale: newScale }, token);",
    "    if (!loraLoaded) return;\n\n    try {\n      await generateApi.setLoraScale({ scale: newScale }, token || '');",
)

text = text.replace(
    "    if (!token || !loraLoaded) return;\n    const newEnabled = !loraEnabled;\n    setLoraEnabled(newEnabled);\n    try {\n      await generateApi.toggleLora({ enabled: newEnabled }, token);",
    "    if (!loraLoaded) return;\n    const newEnabled = !loraEnabled;\n    setLoraEnabled(newEnabled);\n    try {\n      await generateApi.toggleLora({ enabled: newEnabled }, token || '');",
)

# 4) UI: select inside LoRA panel after path label
old_ui = """                <div className="space-y-2">
                  <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{t('loraPath')}</label>
                  <input
                    type="text"
                    value={loraPath}
                    onChange={(e) => setLoraPath(e.target.value)}
                    placeholder={t('loraPathPlaceholder')}
                    className="w-full bg-zinc-50 dark:bg-black/20 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-pink-500 dark:focus:border-pink-500 transition-colors"
                  />
                </div>"""

new_ui = """                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Trained adapters</label>
                    <button
                      type="button"
                      onClick={() => void fetchLoraAdapters()}
                      className="text-[10px] font-semibold text-zinc-500 hover:text-pink-500 transition-colors"
                    >
                      Refresh list
                    </button>
                  </div>
                  <select
                    id="ace-lora-adapter-select"
                    value={loraAdapters.some(a => a.path === loraPath) ? loraPath : ''}
                    onChange={(e) => {
                      if (e.target.value) setLoraPath(e.target.value);
                    }}
                    className="w-full bg-zinc-50 dark:bg-black/20 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-900 dark:text-white focus:outline-none focus:border-pink-500 dark:focus:border-pink-500 transition-colors cursor-pointer [&>option]:bg-white [&>option]:dark:bg-zinc-800"
                  >
                    <option value="">{loraAdapters.length ? 'Select trained adapter…' : '(none found — train first)'}</option>
                    {loraAdapters.map((a) => (
                      <option key={a.path} value={a.path}>
                        {a.label}{a.epoch != null ? ` · ep${a.epoch}` : ''}{a.loss != null ? ` · loss ${a.loss}` : ''}
                      </option>
                    ))}
                  </select>
                  {loraListStatus && (
                    <p className="text-[10px] text-zinc-500">{loraListStatus}</p>
                  )}
                  <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{t('loraPath')}</label>
                  <input
                    type="text"
                    value={loraPath}
                    onChange={(e) => setLoraPath(e.target.value)}
                    placeholder="/app/lora_output/final/adapter"
                    className="w-full bg-zinc-50 dark:bg-black/20 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-pink-500 dark:focus:border-pink-500 transition-colors"
                  />
                </div>"""

if old_ui in text:
    text = text.replace(old_ui, new_ui, 1)
    print("Injected adapter select into LoRA panel UI")
else:
    print("WARN: LoRA path UI block not found exact match", file=sys.stderr)
    # try looser insert before loraPath input
    if "{t('loraPath')}" in text and "ace-lora-adapter-select" not in text:
        text = text.replace(
            "{t('loraPath')}",
            "Trained adapters / {t('loraPath')}",
            1,
        )

# Default path for Docker volumes
text = text.replace(
    "useState('./lora_output/final/adapter')",
    "useState('/app/lora_output/final/adapter')",
    1,
)

p.write_text(text)
print(f"OK patched {p}")
