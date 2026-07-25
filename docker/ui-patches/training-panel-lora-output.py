#!/usr/bin/env python3
"""Per-dataset LoRA output folders for TrainingPanel.tsx

IMPORTANT: Never replace the trainingParams useState OBJECT with a string path.
That bug caused Train LoRA to black-screen (ParamSlider value.toFixed on undefined).

Safe changes only:
  - outputDir / exportPath / exportOutputDir string defaults
  - applyDatasetSelection sets trainingParams.outputDir + export paths
  - ParamSlider guards against non-number values

Idempotent via marker ace-lora-output-per-dataset-v2
"""
from pathlib import Path
import re
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
marker = "ace-lora-output-per-dataset-v2"

# --- 0) Repair regression: trainingParams became a bare path string ---
bad_tp = re.compile(
    r"const \[trainingParams, setTrainingParams\] = useState\(\s*['\"]/app/lora_output[^'\"]*['\"]\s*\);"
)
good_tp = """const [trainingParams, setTrainingParams] = useState({
    tensorDir: '/app/datasets/preprocessed_tensors',
    rank: 64,
    alpha: 128,
    dropout: 0.1,
    learningRate: 0.0003,
    epochs: 1000,
    batchSize: 1,
    gradientAccumulation: 1,
    saveEvery: 200,
    shift: 3.0,
    seed: 42,
    outputDir: '/app/lora_output/my_lora_dataset',
    resumeCheckpoint: '' as string,
  });"""
if bad_tp.search(text):
    text = bad_tp.sub(good_tp, text, count=1)
    print("REPAIRED: trainingParams was a string path — restored object defaults")

# Also catch relative-path string form if any
bad_tp2 = re.compile(
    r"const \[trainingParams, setTrainingParams\] = useState\(\s*['\"]\.?/?lora_output[^'\"]*['\"]\s*\);"
)
if bad_tp2.search(text):
    text = bad_tp2.sub(good_tp, text, count=1)
    print("REPAIRED: trainingParams relative string path")

# --- 1) Path defaults inside the OBJECT only (field-level, not whole useState) ---
field_repls = [
    # tensorDir
    ("tensorDir: './datasets/preprocessed_tensors'", "tensorDir: '/app/datasets/preprocessed_tensors'"),
    ('tensorDir: "./datasets/preprocessed_tensors"', 'tensorDir: "/app/datasets/preprocessed_tensors"'),
    # outputDir — prefer per-dataset default name
    ("outputDir: './lora_output'", "outputDir: '/app/lora_output/my_lora_dataset'"),
    ('outputDir: "./lora_output"', 'outputDir: "/app/lora_output/my_lora_dataset"'),
    ("outputDir: '/app/lora_output'", "outputDir: '/app/lora_output/my_lora_dataset'"),
    ('outputDir: "/app/lora_output"', 'outputDir: "/app/lora_output/my_lora_dataset"'),
]
for a, b in field_repls:
    if a in text:
        text = text.replace(a, b)
        print(f"field default: {a} -> {b}")

# exportPath / exportOutputDir are separate string useStates — safe to set
export_repls = [
    ("useState('./lora_output/final_lora')", "useState('/app/lora_output/my_lora_dataset/final')"),
    ('useState("./lora_output/final_lora")', 'useState("/app/lora_output/my_lora_dataset/final")'),
    ("useState('./lora_output')", "useState('/app/lora_output/my_lora_dataset')"),
    ('useState("./lora_output")', 'useState("/app/lora_output/my_lora_dataset")'),
    # already absolute bare root
    ("useState('/app/lora_output')", "useState('/app/lora_output/my_lora_dataset')"),
    ('useState("/app/lora_output")', 'useState("/app/lora_output/my_lora_dataset")'),
]
for a, b in export_repls:
    # Only replace if line is about exportPath or exportOutputDir (avoid accidental hits)
    # Simple global is OK: trainingParams object no longer has bare useState('./lora_output')
    if a in text:
        text = text.replace(a, b)
        print(f"export default: {a}")

# --- 2) applyDatasetSelection: set outputDir on the params OBJECT ---
new_apply = """  const applyDatasetSelection = useCallback((path: string) => {
    if (!path) return;
    const base = path.split('/').pop() || path;
    const name = base.replace(/\\.json$/i, '').replace(/[^a-zA-Z0-9._-]+/g, '_') || 'my_lora_dataset';
    const loraOut = `/app/lora_output/${name}`;
    setDatasetPath(path);
    setSavePath(path);
    setPreprocessDatasetPath(path);
    setUploadDatasetName(name);
    setDatasetSettings(s => ({ ...s, datasetName: name }));
    setTrainingParams(p => ({ ...p, outputDir: loraOut }));
    setExportPath(`${loraOut}/final`);
    setExportOutputDir(loraOut);
  }, []);
  // ace-lora-output-per-dataset-v2
"""

if "const applyDatasetSelection = useCallback" in text:
    text2, n = re.subn(
        r"const applyDatasetSelection = useCallback\(\(path: string\) => \{.*?\}, \[\]\);\s*(?://[^\n]*)?",
        new_apply.strip() + "\n",
        text,
        count=1,
        flags=re.S,
    )
    if n:
        text = text2
        print("Rewrote applyDatasetSelection -> trainingParams.outputDir + export paths")
    else:
        print("WARN: applyDatasetSelection regex miss", file=sys.stderr)
else:
    print("WARN: applyDatasetSelection not found", file=sys.stderr)

# --- 3) Harden ParamSlider (never crash Train tab) ---
old_ps = "{step < 1 ? value.toFixed(2) : value}"
new_ps = "{typeof value === 'number' && !Number.isNaN(value) ? (step < 1 ? value.toFixed(2) : value) : '—'}"
if old_ps in text and "Number.isNaN(value)" not in text:
    text = text.replace(old_ps, new_ps, 1)
    print("Hardened ParamSlider against undefined value")
elif "Number.isNaN(value)" in text:
    print("ParamSlider already hardened")
else:
    print("WARN: ParamSlider pattern not found", file=sys.stderr)

# --- 4) NEVER do blind useState(...lora_output...) -> string (that was the bug) ---
# Intentionally omitted.

if marker not in text:
    text += f"\n// {marker}\n"

p.write_text(text)
print("OK", p)

# Sanity check
if re.search(r"setTrainingParams\]\s*=\s*useState\(\s*['\"]", text):
    print("ERROR: trainingParams still looks like a string useState", file=sys.stderr)
    sys.exit(1)
print("sanity: trainingParams is object-shaped")
