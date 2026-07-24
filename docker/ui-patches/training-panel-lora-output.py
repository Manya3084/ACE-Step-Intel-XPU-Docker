#!/usr/bin/env python3
"""Upgrade TrainingPanel applyDatasetSelection -> /app/lora_output/<dataset_name>.

Runs after training-panel-datasets.py in Dockerfile.ui.
Idempotent via marker ace-lora-output-per-dataset.
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
marker = "ace-lora-output-per-dataset"
if marker in text and "loraOut" in text:
    print("Already has per-dataset LoRA output")
    sys.exit(0)

replacements = [
    ("'./lora_output'", "'/app/lora_output/my_lora_dataset'"),
    ('"./lora_output"', '"/app/lora_output/my_lora_dataset"'),
    ("'/app/lora_output'", "'/app/lora_output/my_lora_dataset'"),
    ('"/app/lora_output"', '"/app/lora_output/my_lora_dataset"'),
]
for a, b in replacements:
    text = text.replace(a, b)

setters = [
    s
    for s in (
        "setOutputDir",
        "setLoraOutputDir",
        "setTrainingOutputDir",
        "setSaveDir",
        "setOutputPath",
        "setTrainOutputDir",
    )
    if s in text
]
calls = "\n".join(f"    {s}(loraOut);" for s in setters)
if not calls:
    calls = "    /* no outputDir setter in this UI build */"

new_apply = f"""  const applyDatasetSelection = useCallback((path: string) => {{\n    if (!path) return;\n    const base = path.split('/').pop() || path;\n    const name = base.replace(/\\.json$/i, '').replace(/[^a-zA-Z0-9._-]+/g, '_') || 'my_lora_dataset';\n    const loraOut = `/app/lora_output/${{name}}`;\n    setDatasetPath(path);\n    setSavePath(path);\n    setPreprocessDatasetPath(path);\n    setUploadDatasetName(name);\n    setDatasetSettings(s => ({{ ...s, datasetName: name }}));\n{calls}\n  }}, []);\n  // {marker}\n"""

if "const applyDatasetSelection = useCallback" in text:
    text2, n = re.subn(
        r"const applyDatasetSelection = useCallback\(\(path: string\) => \{.*?\}, \[\]\);",
        new_apply.strip(),
        text,
        count=1,
        flags=re.S,
    )
    if n:
        text = text2
        print("Rewrote applyDatasetSelection -> /app/lora_output/<dataset>")
    else:
        print("WARN: applyDatasetSelection regex miss", file=sys.stderr)
else:
    print("WARN: applyDatasetSelection not found (dataset patch may have failed)", file=sys.stderr)

for m in list(re.finditer(r"useState\(([^)]*lora_output[^)]*)\)", text)):
    old = m.group(0)
    text = text.replace(old, "useState('/app/lora_output/my_lora_dataset')", 1)
    print("Defaulted useState lora path")

if marker not in text:
    text += f"\n// {marker}\n"

p.write_text(text)
print("OK", p)
print("setters", setters)
