# ACE-Step-Intel-XPU-Docker

**Repo:** [Manya3084/ACE-Step-Intel-XPU-Docker](https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker)  
**Branch:** `intel-xpu-docker`

Run [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) on **Intel Arc GPUs** under **Linux Docker** (including OpenMediaVault / headless NAS), with a **mobile-friendly Spotify-style UI** ([ace-step-ui](https://github.com/fspecii/ace-step-ui)) instead of relying on Gradio alone in a phone browser.

Upstream ACE-Step supports Intel XPU in code and ships Windows `.bat` helpers. Official Docker is **NVIDIA/CUDA-only**. Community Docker images are also NVIDIA-focused. This project fills that gap.

---

## What this project is for

| Goal | How this repo helps |
|------|------------------------|
| Run ACE-Step on **Intel Arc** (e.g. A770 16GB) | Custom `Dockerfile.xpu`, Level Zero / `/dev/dri`, PyTorch XPU nightly |
| Run on a **home server / OMV** | `docker-compose.xpu.yml`, persistent volumes, LAN ports |
| Use a **better UI on mobile** | ace-step-ui as a Compose service (polling-friendly) |
| Keep **full features** working | Gradio API for generation, REST Format endpoint fixes, CORS, ffmpeg/ffprobe, arg alignment |

**Not** a reimplementation of the music model. It is packaging, device support, and UI integration so Arc + Docker users can actually use the same workflow NVIDIA users get out of the box.

---

## Stack

| Service | Image / role | Host ports |
|---------|----------------|------------|
| `acestep-xpu` | ACE-Step 1.5, Gradio + `--enable-api`, Intel XPU | **8001** |
| `acestep-ui` | React/Vite frontend + Express backend | **3003** (UI), **3004** (API) |

```
Phone / browser  →  :3003  (ace-step-ui)
                         │
                         ▼
                    :3004 Express  →  http://acestep-xpu:8001
                         │                 │
                         │                 ├─ Gradio client → /generation_wrapper  (songs)
                         │                 └─ REST POST /format_input              (AI Format)
                         ▼
                    Intel Arc A770 (XPU) via /dev/dri
```

---

## Hardware tested

| GPU | VRAM | Notes |
|-----|------|--------|
| **Intel Arc A770** | 16GB | Primary target; DiT turbo + 1.7B LM + CPU offload |

Other Arc A/B series with working host Level Zero drivers should work with the same image; adjust LM size / offload if VRAM is lower.

**Host requirements**

- Linux with Intel GPU compute drivers (Level Zero)
- Docker + Compose
- Device nodes passed through: `/dev/dri`
- Enough disk for models (~10GB+) under `./checkpoints`

---

## Quick start

```bash
git clone https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker.git
cd ACE-Step-Intel-XPU-Docker
git checkout intel-xpu-docker

cp .env.xpu.example .env
# edit .env if needed (ports, model names, secrets)

docker compose -f docker-compose.xpu.yml up -d --build
```

Open on LAN / phone:

```text
http://YOUR_SERVER_IP:3003
```

First boot downloads models and initializes DiT + LM (can take several minutes).

---

## Defaults (A770 16GB)

| Setting | Value |
|---------|--------|
| DiT | `acestep-v15-turbo` |
| LM | `acestep-5Hz-lm-1.7B` |
| LM backend | `pt` (PyTorch; recommended on XPU) |
| CPU offload | enabled (VRAM under 20GB tier) |
| Mode | `gradio-api` (Gradio UI endpoints + API for ace-step-ui) |

See `.env.xpu.example` for the full list.

---

## Verified features (this stack)

| Feature | Status |
|---------|--------|
| XPU detection / generation on Arc A770 | Working |
| Song generation via ace-step-ui → Gradio | Working |
| AI Format (style / lyrics enhance) via `/format_input` | Working (often **~1–2 min** first call with offload) |
| Mobile UI (leave browser and return) | Much more reliable than plain Gradio WebSockets |
| CORS for LAN / mobile | Patched in UI image |
| `ffprobe` for duration metadata | `ffmpeg` installed in UI image |

---

## Useful commands

```bash
# Logs
docker compose -f docker-compose.xpu.yml logs -f acestep-xpu
docker compose -f docker-compose.xpu.yml logs -f acestep-ui

# Rebuild after pulling
docker compose -f docker-compose.xpu.yml down
git pull origin intel-xpu-docker
docker compose -f docker-compose.xpu.yml up -d --build

# Health / Format smoke tests
curl -sS http://127.0.0.1:8001/health
curl -sS -m 300 -X POST http://127.0.0.1:8001/format_input \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"pop rock","lyrics":"walking down the street"}'
```

---

## Key files

| File | Purpose |
|------|---------|
| `Dockerfile.xpu` | Intel GPU packages, XPU PyTorch, Gradio+API entrypoint, Format route hardening |
| `Dockerfile.ui` | Clones ace-step-ui, CORS, Gradio arg map, ffmpeg, format timeout |
| `docker-compose.xpu.yml` | Both services, `/dev/dri`, ports 8001 / 3003 / 3004 |
| `.env.xpu.example` | A770-oriented defaults |
| `README-DOCKER-XPU.md` | This document |
| `FORK.md` | Short “why this repo exists” |

---

## Troubleshooting

**XPU not detected in container**
- Host: `clinfo`, `intel_gpu_top`, recent Intel compute drivers
- Compose must pass `/dev/dri`
- PyTorch must report `+xpu` and `torch.xpu.is_available() == True`

**Format button spins a long time**
- Expected on first use: load 1.7B → generate → offload can take **1–3 minutes**
- Backend is fine if `curl` to `/format_input` eventually returns `code: 200`

**UI 500 on “Get Started” / CORS**
- Rebuild UI: `docker compose -f docker-compose.xpu.yml up -d --build acestep-ui`

**Generation parameter errors (sampler / scoreScale)**
- UI image patches `buildGradioArgs` to match current Gradio `/generation_wrapper` schema; rebuild UI after pulling

**`pull access denied` for `acestep-xpu` / `acestep-ui`**
- Those tags are **local builds**, not Docker Hub. Always `up --build` (do not expect a public pull)

---

## Relation to upstream

- Upstream project: [ace-step/ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5)
- Upstream XPU on Windows: see their `README-XPU.md` / `setup_xpu.bat`
- This repo does **not** replace the model or training code; it adds a **Linux Docker + Arc + ace-step-ui** path that upstream does not ship

Contributions and issue reports for Arc/OMV Docker packaging are welcome.
