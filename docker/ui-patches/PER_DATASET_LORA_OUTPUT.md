# Per-dataset LoRA output folders

Training adapters are written under:

```text
/app/lora_output/<dataset_name>/final/adapter/
/app/lora_output/<dataset_name>/checkpoints/epoch_*/adapter/
```

`<dataset_name>` is taken from the dataset JSON filename (e.g. `Leaf_lora.json` → `Leaf_lora`).

## UI behaviour

- Training panel dataset dropdown scans `/app/datasets/*.json`.
- Selecting a dataset sets:
  - dataset / save / preprocess paths to that JSON
  - `trainingParams.outputDir` → `/app/lora_output/<name>`
  - export paths under the same folder
- Create panel LoRA picker lists adapters with labels like `Leaf_lora/final`.

## Critical fix (Train LoRA black screen)

`training-panel-lora-output.py` must **never** replace the entire
`trainingParams` `useState({ rank, batchSize, outputDir, ... })` object with a
string path. That made `ParamSlider` call `.toFixed()` on `undefined` and blanked
the Train tab.

Safe approach: only change the `outputDir` **field** (and export string states).
