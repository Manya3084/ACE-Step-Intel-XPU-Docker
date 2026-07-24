#!/usr/bin/env python3
"""Patch TrainingPanel.tsx — dataset JSON dropdown + chain per-dataset LoRA folders."""
from pathlib import Path
import sys
import runpy

p = Path("components/TrainingPanel.tsx")
if not p.is_file():
    for c in Path(".").rglob("TrainingPanel.tsx"):
        p = c
        break
if not p.is_file():
    print("TrainingPanel.tsx not found", file=sys.stderr)
    sys.exit(1)

text = p.read_text()
already = "ace-dataset-select" in text or "fetchDatasetList" in text

if already:
    print("TrainingPanel already has dataset scanner — skip inject, chain output patch")
else:
    old_state = """  const [datasetPath, setDatasetPath] = useState('./datasets/my_lora_dataset.json');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
    new_state = """  const [datasetPath, setDatasetPath] = useState('/app/datasets/my_lora_dataset.json');
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string; samples?: number; mtime?: string }[]>([]);
  const [datasetListStatus, setDatasetListStatus] = useState('');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
    if old_state in text:
        text = text.replace(old_state, new_state, 1)
        print("Added availableDatasets state")
    else:
        old_state2 = """  const [datasetPath, setDatasetPath] = useState('/app/datasets/my_lora_dataset.json');
  const [datasetLoaded, setDatasetLoaded] = useState(false);"""
        if old_state2 in text:
            text = text.replace(old_state2, new_state, 1)
            print("Added availableDatasets state (abs path)")
        else:
            print("WARN: datasetPath state not found", file=sys.stderr)

    text = text.replace("useState('./datasets/my_lora_dataset.json')", "useState('/app/datasets/my_lora_dataset.json')")
    text = text.replace("useState('./datasets/preprocessed_tensors')", "useState('/app/datasets/preprocessed_tensors')")

    marker = "  const populateSampleFields = (sample: TrainingSample) => {"
    fetch_block = r'''
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
    const name = base.replace(/\.json$/i, '').replace(/[^a-zA-Z0-9._-]+/g, '_') || 'my_lora_dataset';
    const loraOut = `/app/lora_output/${name}`;
    setDatasetPath(path);
    setSavePath(path);
    setPreprocessDatasetPath(path);
    setUploadDatasetName(name);
    setDatasetSettings(s => ({ ...s, datasetName: name }));
    // output dir setters filled by training-panel-lora-output.py if present
  }, []);

  useEffect(() => { void fetchDatasetList(); }, [fetchDatasetList]);

  const populateSampleFields = (sample: TrainingSample) => {'''
    if marker in text:
        text = text.replace(marker, fetch_block, 1)
        print("Added fetchDatasetList")
    p.write_text(text)
    print(f"OK base dataset patch {p}")

# Always chain per-dataset LoRA output folder logic when the sibling patch exists
sib = Path("/tmp/training-panel-lora-output.py")
if sib.is_file():
    try:
        runpy.run_path(str(sib), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
else:
    print("WARN: /tmp/training-panel-lora-output.py missing — copy it in Dockerfile.ui")
