# LoRA picker wiring

Add to `Dockerfile.ui` after draft-persist:

```dockerfile
COPY docker/ui-patches/lora-picker.py /tmp/lora-picker.py
RUN python3 /tmp/lora-picker.py
```

Ensure start script copies `ace-xpu-lora-picker.js`:

```bash
for f in ace-xpu-restart.js ace-xpu-console.js ace-xpu-draft.js ace-xpu-lora-picker.js; do
```

Rebuild:

```bash
sudo git pull origin main
sudo docker compose -f docker-compose.xpu.yml build --no-cache acestep-ui
sudo docker compose -f docker-compose.xpu.yml up -d --force-recreate acestep-ui
```

UI: bottom-right **LoRA picker** — Refresh, select epoch/final, scale, Load / Unload.
