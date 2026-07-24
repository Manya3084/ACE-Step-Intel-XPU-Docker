# Per-dataset LoRA output folders

## Rule

| Dataset JSON | LoRA output root |
|--------------|------------------|
| `/app/datasets/Leaf_lora.json` | `/app/lora_output/Leaf_lora/` |
| `/app/datasets/my_lora_dataset.json` | `/app/lora_output/my_lora_dataset/` |

Tree after training:

```text
/app/lora_output/Leaf_lora/final/adapter/
/app/lora_output/Leaf_lora/checkpoints/epoch_1000_loss_0.04/adapter/
/app/lora_output/my_lora_dataset/final/adapter/
```

Create → LoRA list labels them as `Leaf_lora / final`, `Leaf_lora / epoch_1000_…`.

## Wire into Dockerfile.ui

Add **before** `RUN python3 /tmp/training-panel-datasets.py`:

```dockerfile
COPY docker/ui-patches/training-panel-lora-output.py /tmp/training-panel-lora-output.py
```

`training-panel-datasets.py` chains `runpy` on that file when present.

Then rebuild UI:

```bash
git pull origin main
docker compose -f docker-compose.xpu.yml up -d --build acestep-ui
```

## Until rebuild: set path by hand

In Training → LoRA / output path field, type:

```text
/app/lora_output/Leaf_lora
```

(use your dataset name). Then start training.

## Migrate an old flat run

```bash
docker exec acestep-xpu bash -c '
  NAME=legacy_run   # or Leaf_lora if you know which dataset it was
  mkdir -p /app/lora_output/$NAME
  for d in final checkpoints final_lora; do
    [ -e /app/lora_output/$d ] || continue
    mv /app/lora_output/$d /app/lora_output/$NAME/
  done
  ls -la /app/lora_output/
'
```
