# ACE-Step 1.5 + ace-step-ui — Docker on Intel Arc / XPU

Full stack for **Intel Arc A770 16GB** on Linux / OpenMediaVault:

| Service | Role | Port |
|---------|------|------|
| `acestep-xpu` | ACE-Step API (Intel XPU) | 8001 |
| `acestep-ui` | Spotify-style web UI (mobile-friendly) | **3003** |
| `acestep-ui` backend | Express API for the UI | **3004** |

Gradio is no longer the primary UI.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile.xpu` | ACE-Step with XPU PyTorch + Level Zero |
| `Dockerfile.ui` | ace-step-ui frontend |
| `docker-compose.xpu.yml` | Both services |
| `.env.xpu.example` | A770-tuned defaults |

## Host prerequisites (OMV / Debian / Ubuntu)

1. Intel Arc drivers working (`clinfo` / `intel_gpu_top` sees the A770)
2. Level Zero packages (via Intel GPU repo if needed)
3. User in `video` + `render` groups
4. Docker + Compose

## Quick start (full stack)

```bash
git clone https://github.com/Manya3084/ACE-Step-1.5.git
cd ACE-Step-1.5
git checkout intel-xpu-docker

cp .env.xpu.example .env

# Optional but recommended: set your LAN URL for mobile
# echo 'FRONTEND_URL=http://192.168.x.x:3003' >> .env
# echo 'VITE_API_URL=http://192.168.x.x:3004' >> .env

docker compose -f docker-compose.xpu.yml up -d --build
```

Then open on phone or desktop:

```
http://YOUR_OMV_IP:3003
```

API (if you need it directly):

```
http://YOUR_OMV_IP:8001
```

## Useful commands

```bash
# Logs
docker compose -f docker-compose.xpu.yml logs -f

# Restart just the UI
docker compose -f docker-compose.xpu.yml restart acestep-ui

# Stop everything
docker compose -f docker-compose.xpu.yml down
```

## A770 defaults

- DiT: `acestep-v15-turbo`
- LM: `acestep-5Hz-lm-1.7B`
- CPU offload: on
- Mode: API only

## Mobile tips

- Use `http://YOUR_OMV_IP:3003` (not localhost)
- Progress survives switching apps (API polling, not Gradio WebSockets)
- First start of `acestep-xpu` is slow while models download

## Troubleshooting

**UI can't reach API**
- Check `docker logs acestep-xpu` — API should be on 8001
- Inside Docker network the UI uses `http://acestep-xpu:8001`

**XPU not detected**
- Host: `clinfo` / `intel_gpu_top`
- Container must have `/dev/dri`
- PyTorch version should contain `+xpu`, not `+cu`

**Out of memory**
- Keep turbo + 1.7B + offload
- Close other GPU workloads
