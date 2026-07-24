#!/usr/bin/env python3
"""Patch TrainingPanel.tsx — scan /app/datasets/*.json and pick via dropdown.

Adds:
- state + fetch of GET /api/training/datasets (no JWT needed under OPEN_LOCAL_AUTH)
- dropdown above Load Existing Dataset path
- same picker for Preprocess dataset path
- selecting fills datasetPath / savePath / preprocessDatasetPath / datasetName
"""
from pathlib import Path
import sys

p = Path("components/TrainingPanel.tsx")
if not p.is_file():
    for c in Path(".").rglob("TrainingPanel.tsx"):
        p = c
        break
if not p.is_file():
    print("TrainingPanel.tsx not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
if "ace-dataset-select" in text or "fetchDatasetList" in text:
    print("TrainingPanel already has dataset scanner")
    sys.exit(0)

# 1) State after datasetPath state block
old_state = """  const [datasetPath, setDatasetPath] = useState('./datasets/my_lora_dataset.json');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
new_state = """  const [datasetPath, setDatasetPath] = useState('/app/datasets/my_lora_dataset.json');
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string; samples?: number; mtime?: string }[]>([]);
  const [datasetListStatus, setDatasetListStatus] = useState('');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
if old_state not in text:
    old_state2 = """  const [datasetPath, setDatasetPath] = useState('/app/datasets/my_lora_dataset.json');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
    if old_state2 in text:
        text = text.replace(
            old_state2,
            """  const [datasetPath, setDatasetPath] = useState('/app/datasets/my_lora_dataset.json');
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string; samples?: number; mtime?: string }[]>([]);
  const [datasetListStatus, setDatasetListStatus] = useState('');
  const [datasetLoaded, setDatasetLoaded] = useState(false);""",
            1,
        )
        print("Added availableDatasets state (abs path)")
    else:
        print("WARN: datasetPath state not found", file=sys.stderr)
else:
    text = text.replace(old_state, new_state, 1)
    print("Added availableDatasets state")

text = text.replace(
    "useState('./datasets/my_lora_dataset.json')",
    "useState('/app/datasets/my_lora_dataset.json')",
)
text = text.replace(
    "useState('./datasets/preprocessed_tensors')",
    "useState('/app/datasets/preprocessed_tensors')",
)
text = text.replace(
    'placeholder="./datasets/my_dataset.json"',
    'placeholder="/app/datasets/my_lora_dataset.json"',
)
text = text.replace(
    'placeholder="./datasets/my_lora_dataset.json"',
    'placeholder="/app/datasets/my_lora_dataset.json"',
)

marker = "  const populateSampleFields = (sample: TrainingSample) => {"
fetch_block = r'''
  // ACE-Step-Intel-XPU-Docker: list dataset JSON files under /app/datasets
  const fetchDatasetList = useCallback(async () => {
    setDatasetListStatus('Scanning…');
    try {
      const res = await fetch('/api/training/datasets');
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const list = Array.isArray(data.datasets) ? data.datasets : [];
      setAvailableDatasets(list);
      setDatasetListStatus(list.length ? `${list.length} dataset(s)` : 'No .json under /app/datasets');
    } catch (e) {
      setDatasetListStatus(e instanceof Error ? e.message : 'List failed');
    }
  }, []);

  const applyDatasetSelection = useCallback((path: string) => {
    if (!path) return;
    const base = path.split('/').pop() || path;
    const name = base.replace(/\.json$/i, '');
    setDatasetPath(path);
    setSavePath(path);
    setPreprocessDatasetPath(path);
    setUploadDatasetName(name);
    setDatasetSettings(s => ({ ...s, datasetName: name }));
  }, []);

  useEffect(() => {
    void fetchDatasetList();
  }, [fetchDatasetList]);

  const populateSampleFields = (sample: TrainingSample) => {'''

if marker in text:
    text = text.replace(marker, fetch_block, 1)
    print("Added fetchDatasetList")
else:
    print("WARN: populateSampleFields marker missing", file=sys.stderr)

old_load = '''            <Section title={t('loadExistingDataset')}>
              <div className="flex gap-2">
                <input type="text" value={datasetPath} onChange={e => setDatasetPath(e.target.value)} className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" placeholder="/app/datasets/my_lora_dataset.json" />
                <button onClick={handleLoadDataset} disabled={datasetLoading} className="px-3 py-1.5 bg-pink-500/20 hover:bg-pink-500/30 text-pink-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                  {datasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                  {t('loadDataset')}
                </button>
              </div>
              {datasetStatus && <p className="text-xs text-zinc-400 mt-1.5 break-words">{datasetStatus}</p>}
            </Section>'''

old_load_alt = '''            <Section title={t('loadExistingDataset')}>
              <div className="flex gap-2">
                <input type="text" value={datasetPath} onChange={e => setDatasetPath(e.target.value)} className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" placeholder="./datasets/my_dataset.json" />
                <button onClick={handleLoadDataset} disabled={datasetLoading} className="px-3 py-1.5 bg-pink-500/20 hover:bg-pink-500/30 text-pink-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                  {datasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                  {t('loadDataset')}
                </button>
              </div>
              {datasetStatus && <p className="text-xs text-zinc-400 mt-1.5 break-words">{datasetStatus}</p>}
            </Section>'''

new_load = '''            <Section title={t('loadExistingDataset')}>
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <label className="text-[10px] text-zinc-500 font-medium">Saved datasets (/app/datasets)</label>
                <button type="button" onClick={() => void fetchDatasetList()} className="text-[10px] font-semibold text-zinc-500 hover:text-pink-400 transition-colors flex items-center gap-1">
                  <RefreshCw size={10} /> Refresh
                </button>
              </div>
              <select
                id="ace-dataset-select"
                value={availableDatasets.some(d => d.path === datasetPath) ? datasetPath : ''}
                onChange={(e) => {
                  if (e.target.value) applyDatasetSelection(e.target.value);
                }}
                className="w-full mb-2 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50 cursor-pointer [&>option]:bg-zinc-900"
              >
                <option value="">{availableDatasets.length ? 'Select a dataset…' : '(none found — save one first)'}</option>
                {availableDatasets.map((d) => (
                  <option key={d.path} value={d.path}>
                    {d.name}{d.samples != null ? ` · ${d.samples} sample(s)` : ''}
                  </option>
                ))}
              </select>
              {datasetListStatus && <p className="text-[10px] text-zinc-500 mb-1.5">{datasetListStatus}</p>}
              <div className="flex gap-2">
                <input type="text" value={datasetPath} onChange={e => setDatasetPath(e.target.value)} className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" placeholder="/app/datasets/my_lora_dataset.json" />
                <button onClick={handleLoadDataset} disabled={datasetLoading} className="px-3 py-1.5 bg-pink-500/20 hover:bg-pink-500/30 text-pink-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                  {datasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                  {t('loadDataset')}
                </button>
              </div>
              {datasetStatus && <p className="text-xs text-zinc-400 mt-1.5 break-words">{datasetStatus}</p>}
            </Section>'''

if old_load in text:
    text = text.replace(old_load, new_load, 1)
    print("Injected dataset dropdown (Load Existing)")
elif old_load_alt in text:
    text = text.replace(old_load_alt, new_load, 1)
    print("Injected dataset dropdown (Load Existing, alt)")
else:
    print("WARN: Load Existing Dataset block not found", file=sys.stderr)

old_pp = '''                  <div className="mb-3 p-2 bg-white/[0.02] border border-white/5 rounded-lg space-y-2">
                    <label className="text-[10px] text-zinc-500 font-medium">Load Existing Dataset</label>
                    <div className="flex gap-2">
                      <input type="text" value={preprocessDatasetPath} onChange={e => setPreprocessDatasetPath(e.target.value)} placeholder="/app/datasets/my_lora_dataset.json" className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" />
                      <button onClick={handleLoadDatasetForPreprocess} disabled={preprocessDatasetLoading} className="px-3 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                        {preprocessDatasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                        Load
                      </button>
                    </div>
                    {preprocessDatasetStatus && <p className="text-[10px] text-zinc-400 break-words">{preprocessDatasetStatus}</p>}
                  </div>'''

old_pp_alt = '''                  <div className="mb-3 p-2 bg-white/[0.02] border border-white/5 rounded-lg space-y-2">
                    <label className="text-[10px] text-zinc-500 font-medium">Load Existing Dataset</label>
                    <div className="flex gap-2">
                      <input type="text" value={preprocessDatasetPath} onChange={e => setPreprocessDatasetPath(e.target.value)} placeholder="./datasets/my_lora_dataset.json" className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" />
                      <button onClick={handleLoadDatasetForPreprocess} disabled={preprocessDatasetLoading} className="px-3 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                        {preprocessDatasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                        Load
                      </button>
                    </div>
                    {preprocessDatasetStatus && <p className="text-[10px] text-zinc-400 break-words">{preprocessDatasetStatus}</p>}
                  </div>'''

new_pp = '''                  <div className="mb-3 p-2 bg-white/[0.02] border border-white/5 rounded-lg space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-[10px] text-zinc-500 font-medium">Load Existing Dataset</label>
                      <button type="button" onClick={() => void fetchDatasetList()} className="text-[10px] text-zinc-500 hover:text-pink-400">Refresh</button>
                    </div>
                    <select
                      id="ace-dataset-select-preprocess"
                      value={availableDatasets.some(d => d.path === preprocessDatasetPath) ? preprocessDatasetPath : ''}
                      onChange={(e) => {
                        if (e.target.value) {
                          applyDatasetSelection(e.target.value);
                          setPreprocessDatasetPath(e.target.value);
                        }
                      }}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50 cursor-pointer [&>option]:bg-zinc-900"
                    >
                      <option value="">{availableDatasets.length ? 'Select a dataset…' : '(none found)'}</option>
                      {availableDatasets.map((d) => (
                        <option key={d.path} value={d.path}>
                          {d.name}{d.samples != null ? ` · ${d.samples} sample(s)` : ''}
                        </option>
                      ))}
                    </select>
                    <div className="flex gap-2">
                      <input type="text" value={preprocessDatasetPath} onChange={e => setPreprocessDatasetPath(e.target.value)} placeholder="/app/datasets/my_lora_dataset.json" className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-pink-500/50" />
                      <button onClick={handleLoadDatasetForPreprocess} disabled={preprocessDatasetLoading} className="px-3 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg text-xs font-medium flex items-center gap-1.5 disabled:opacity-50">
                        {preprocessDatasetLoading ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                        Load
                      </button>
                    </div>
                    {preprocessDatasetStatus && <p className="text-[10px] text-zinc-400 break-words">{preprocessDatasetStatus}</p>}
                  </div>'''

if old_pp in text:
    text = text.replace(old_pp, new_pp, 1)
    print("Injected dataset dropdown (Preprocess)")
elif old_pp_alt in text:
    text = text.replace(old_pp_alt, new_pp, 1)
    print("Injected dataset dropdown (Preprocess, alt)")
else:
    print("WARN: Preprocess dataset block not found", file=sys.stderr)

p.write_text(text)
print(f"OK patched {p}")
