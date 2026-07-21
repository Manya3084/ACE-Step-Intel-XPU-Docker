# ACE-Step 1.5 + ace-step-ui — Docker on Intel Arc / XPU

Full stack for **Intel Arc A770 16GB** on Linux / OpenMediaVault:

| Service | Role | Host port |
|---------|------|-----------|
| `acestep-xpu` | ACE-Step API (Intel XPU) | **8001** |
| `acestep-ui` | Spotify-style web UI | **3003** |
| `acestep-ui` backend | Express (via Vite proxy) | **3004** |

## Quick start

```bash
git clone https://github.com/Manya3084/ACE-Step-1.5.git
cd ACE-Step-1.5
git checkout intel-xpu-docker

cp .env.xpu.example .env

docker compose -f docker-compose.xpu.yml up -d --build
```

Open on phone/desktop:

```
http://YOUR_OMV_IP:3003
```

## Useful commands

```bash
docker compose -f docker-compose.xpu.yml logs -f acestep-ui
docker compose -f docker-compose.xpu.yml logs -f acestep-xpu
docker compose -f docker-compose.xpu.yml restart acestep-ui
docker compose -f docker-compose.xpu.yml down
```

## A770 defaults

- DiT: `acestep-v15-turbo`
- LM: `acestep-5Hz-lm-1.7B`
- CPU offload: on
- Mode: API only

## Troubleshooting

**500 on "Get Started" / name entry**
- Rebuild UI after the proxy fix: `docker compose -f docker-compose.xpu.yml up -d --build acestep-ui`
- Check logs: `docker logs acestep-ui`

**UI can't reach ACE-Step API**
- `docker logs acestep-xpu` — should show API on 8001
- Internal URL is `http://acestep-xpu:8001`

**XPU not detected**
- Host: `clinfo` / `intel_gpu_top`
- Container needs `/dev/dri`
- PyTorch version must contain `+xpu`
