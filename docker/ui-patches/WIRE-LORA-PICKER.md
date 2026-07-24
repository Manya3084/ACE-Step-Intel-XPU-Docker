# LoRA picker wiring

Already included in `Dockerfile.ui` via `lora-picker.py`.

**UI:** adapter list is injected **into the existing left-sidebar LoRA settings** (not a floating panel).

- Dropdown of `/app/lora_output` adapters (`final`, `epoch_*`)
- Refresh / Load / Unload
- Syncs into the native LoRA path field when present

Rebuild UI only:

```bash
sudo git pull origin main
sudo docker compose -f docker-compose.xpu.yml build --no-cache acestep-ui
sudo docker compose -f docker-compose.xpu.yml up -d --force-recreate acestep-ui
```
