# ACE-Step-Intel-XPU-Docker

**Repo:** [Manya3084/ACE-Step-Intel-XPU-Docker](https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker)  
**Branch:** `intel-xpu-docker`

Run [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) on **Intel Arc GPUs** under **Linux Docker** (including OpenMediaVault / headless NAS), with a **mobile-friendly Spotify-style UI** ([ace-step-ui](https://github.com/fspecii/ace-step-ui)) instead of relying on Gradio alone in a phone browser.

Upstream ACE-Step supports Intel XPU in code and ships Windows `.bat` helpers. Official Docker is **NVIDIA/CUDA-only**. Community Docker images are also NVIDIA-focused. This project fills that gap.

---

## What this project is for

| Goal | How this repo helps |
|------|------------------------|
| Run ACE-Step on **Intel Arc** (A/B series + Pro) | Custom `Dockerfile.xpu`, Level Zero / `/dev/dri`, PyTorch XPU nightly |
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
                    Intel Arc (XPU) via /dev/dri
```

---

## GPU settings recommendations (Arc A / B / Pro)

Recommendations are driven primarily by **VRAM**. Always use **`ACESTEP_LLM_BACKEND=pt`** on Intel XPU (vLLM is CUDA-oriented). DiT default is **`acestep-v15-turbo`** for speed; switch to `acestep-v15-sft` / base only if you have headroom and want quality over speed.

Only the **A770 16GB** row is fully verified on this Docker stack so far. Other rows are reasoned from upstream VRAM tiers + public card memory sizes.

### Consumer — Arc A-series (Alchemist)

| GPU | VRAM | DiT | LM | CPU offload | Notes |
|-----|------|-----|-----|-------------|--------|
| **A310** | 4GB | `acestep-v15-turbo` | **off** (`INIT_LLM` false / no LM) | **on** | DiT-only; shortest songs; tight |
| **A380** | 6GB | `acestep-v15-turbo` | off, or `0.6B` if stable | **on** | Prefer DiT-only first |
| **A580** | 8GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` | **on** | Batch 1; Format will be slow |
| **A750** | 8GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` | **on** | Same as A580; more cores, not more VRAM |
| **A770** (8GB) | 8GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` | **on** | Treat like A750 |
| **A770** (16GB) | 16GB | `acestep-v15-turbo` | **`acestep-5Hz-lm-1.7B`** | **on** | **Primary verified config** |

### Consumer — Arc B-series (Battlemage)

| GPU | VRAM | DiT | LM | CPU offload | Notes |
|-----|------|-----|-----|-------------|--------|
| **B570** | 10GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` (try `1.7B` if stable) | **on** | Start with 0.6B; OOM → stay on 0.6B |
| **B580** | 12GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` or **`1.7B`** | **on** | 1.7B usually OK with offload; good value tier |

### Professional — Arc Pro A-series

| GPU | VRAM | DiT | LM | CPU offload | Notes |
|-----|------|-----|-----|-------------|--------|
| **Pro A30M** | 4GB | `acestep-v15-turbo` | **off** | **on** | Mobile Pro; DiT-only |
| **Pro A40 / A50** | 6GB | `acestep-v15-turbo` | off or `0.6B` | **on** | Same class as A380 |
| **Pro A60M** | 8GB | `acestep-v15-turbo` | `acestep-5Hz-lm-0.6B` | **on** | Mobile workstation |
| **Pro A60** | 12GB | `acestep-v15-turbo` | `0.6B` or **`1.7B`** | **on** | Same ballpark as B580 |

### Professional — Arc Pro B-series & Flex

| GPU | VRAM | DiT | LM | CPU offload | Notes |
|-----|------|-----|-----|-------------|--------|
| **Pro B50** | (check SKU) | `acestep-v15-turbo` | size by VRAM table below | by VRAM | Confirm VRAM with `clinfo` / vendor sheet |
| **Pro B60** | ~24GB | turbo or sft | **`1.7B`** or try **`4B`** | optional | Headroom for larger LM / less offload |
| **Pro B65 / B70** | 32GB | turbo / sft / XL* | **`1.7B`** or **`4B`** | off if stable | Best Pro quality tier |
| **Flex 140** | 12GB | `acestep-v15-turbo` | `0.6B` or `1.7B` | **on** | Data-center / server Arc |
| **Flex 170** | 16GB | `acestep-v15-turbo` | **`1.7B`** | **on** | Same class as A770 16GB |

\*XL DiT (`acestep-v15-xl-*`) needs more VRAM (roughly ≥12GB with aggressive offload, ≥20GB comfortable). Prefer turbo 2B on ≤16GB cards.

### Quick VRAM cheat sheet (any Intel XPU)

| VRAM | Suggested LM | Offload | Batch |
|------|--------------|---------|-------|
| ≤6GB | none | on | 1 |
| 8GB | 0.6B | on | 1 |
| 10–12GB | 0.6B → try 1.7B | on | 1 |
| 16GB | **1.7B** | on | 1–2 |
| 24GB | 1.7B or 4B | optional | 2+ |
| 32GB+ | 4B | optional / off | 2–4 |

### `.env` knobs

```bash
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B   # or 0.6B / 4B / empty for DiT-only
ACESTEP_LLM_BACKEND=pt
ACESTEP_OFFLOAD_TO_CPU=true                 # false only if VRAM is comfortable
ACESTEP_INIT_SERVICE=true
```

After changing models, recreate the XPU container so weights re-init:

```bash
docker compose -f docker-compose.xpu.yml up -d --force-recreate acestep-xpu
```

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
# edit .env for your GPU (see tables above)

docker compose -f docker-compose.xpu.yml up -d --build
```

Open on LAN / phone:

```text
http://YOUR_SERVER_IP:3003
```

First boot downloads models and initializes DiT + LM (can take several minutes).

---

## Defaults shipped in `.env.xpu.example` (A770 16GB)

| Setting | Value |
|---------|--------|
| DiT | `acestep-v15-turbo` |
| LM | `acestep-5Hz-lm-1.7B` |
| LM backend | `pt` |
| CPU offload | enabled |
| Mode | `gradio-api` |

---

## Verified features (this stack)

| Feature | Status |
|---------|--------|
| XPU detection / generation on Arc A770 16GB | Working |
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

**OOM / crashes on smaller cards**
- Drop to `acestep-5Hz-lm-0.6B` or disable LM
- Keep `ACESTEP_OFFLOAD_TO_CPU=true`
- Batch size 1; shorter durations

**Format button spins a long time**
- Expected on first use with 1.7B + offload: **1–3 minutes**
- Backend is fine if `curl` to `/format_input` eventually returns `code: 200`

**UI 500 on “Get Started” / CORS**
- Rebuild UI: `docker compose -f docker-compose.xpu.yml up -d --build acestep-ui`

**Generation parameter errors (sampler / scoreScale)**
- UI image patches `buildGradioArgs` to match current Gradio `/generation_wrapper` schema; rebuild UI after pulling

**`pull access denied` for `acestep-xpu` / `acestep-ui`**
- Those tags are **local builds**, not Docker Hub. Always `up --build`

---

## Relation to upstream

- Upstream project: [ace-step/ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5)
- Upstream XPU on Windows: see their `README-XPU.md` / `setup_xpu.bat`
- This repo does **not** replace the model or training code; it adds a **Linux Docker + Arc + ace-step-ui** path that upstream does not ship

Contributions and issue reports for Arc/OMV Docker packaging are welcome.
