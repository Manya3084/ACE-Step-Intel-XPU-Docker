# ACE-Step-Intel-XPU-Docker

**Repo:** [Manya3084/ACE-Step-Intel-XPU-Docker](https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker)  
**Branch:** `main` (also `intel-xpu-docker`)

Run [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) on **Intel Arc GPUs** under **Linux Docker** (OpenMediaVault, TrueNAS SCALE, or any headless host), with a **mobile-friendly Spotify-style UI** ([ace-step-ui](https://github.com/fspecii/ace-step-ui)).

Upstream ACE-Step supports Intel XPU in code and ships Windows `.bat` helpers. Official Docker is **NVIDIA/CUDA-only**. This project fills the Arc + Linux Docker gap.

---

## Stack

| Service | Role | Host ports |
|---------|------|------------|
| `acestep-xpu` | ACE-Step 1.5, Gradio + API, Intel XPU | **8001** |
| `acestep-ui` | React UI + Express | **3003** (UI), **3004** (API) |

```
Phone / browser  →  :3003  (ace-step-ui)
                         │
                         ▼
                    :3004 Express  →  http://acestep-xpu:8001
                         │                 │
                         │                 ├─ Gradio → generation
                         │                 └─ REST → Format / health
                         ▼
                    Intel Arc via /dev/dri
```

Shared volumes (compose): `./datasets`, `./lora_output`, `./checkpoints`.

---

## Quick start (OMV / generic Linux)

```bash
git clone https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker.git
cd ACE-Step-Intel-XPU-Docker
git checkout main

cp .env.xpu.example .env
# edit .env for your GPU

docker compose -f docker-compose.xpu.yml up -d --build
```

Open: `http://YOUR_SERVER_IP:3003`

First boot downloads models (several minutes).

### Host requirements

- Linux with Intel GPU compute drivers (Level Zero)
- Docker + Compose
- `/dev/dri` passed into the container
- Disk for `./checkpoints` (~10GB+)

---

## LoRA training (XPU) — Save → Preprocess → Train

Verified on **Arc A770 16GB**.

### 1. Save dataset (UI)

- Upload audio under the Training tab (files land in `/app/datasets/uploads/<name>/`).
- Dataset name e.g. `my_lora_dataset`.
- **Save dataset** writes `/app/datasets/<name>.json` via a **local filesystem route** (upstream `/v1/dataset/save` is not available in this stack).

### 2. Convert to WAV if needed

TorchCodec is **not** used on pure XPU (CUDA `libnvrtc`). Prefer **WAV 48 kHz stereo**:

```bash
docker exec acestep-xpu bash -c '
  cd /app/datasets/uploads/my_lora_dataset
  for f in *.mp3 *.flac; do
    [ -f "$f" ] || continue
    ffmpeg -y -i "$f" -ar 48000 -ac 2 "${f%.*}.wav"
  done
'
```

`soundfile` + `ffmpeg` are baked into `Dockerfile.xpu`.

### 3. Preprocess → `.pt` tensors

Script: `docker/ui-patches/preprocess_dataset.py` (copied to `/app/datasets/_tools/preprocess_dataset.py` on start).

```bash
docker exec -w /app acestep-xpu bash -c '
  . /app/.venv/bin/activate
  export ACESTEP_CHECKPOINTS=/app/checkpoints PYTORCH_DEVICE=xpu ACESTEP_OFFLOAD_TO_CPU=true
  export ACESTEP_CONFIG_PATH=acestep-v15-turbo
  python3 /app/datasets/_tools/preprocess_dataset.py \
    --dataset /app/datasets/my_lora_dataset.json \
    --output /app/datasets/preprocessed_tensors \
    --max-duration 240 --json
'
```

Expect `.pt` files + `manifest.json` under `/app/datasets/preprocessed_tensors`.

### 4. Train

In the UI Training tab:

| Field | Value |
|-------|--------|
| Tensor dir | `/app/datasets/preprocessed_tensors` |
| LoRA output | `/app/lora_output` |
| Batch | `1` (A770 + offload) |
| Rank | start `16–32` |

---

## TrueNAS SCALE installation

TrueNAS **SCALE** (Debian-based) can run this stack with Docker Compose. TrueNAS **CORE** (FreeBSD) is **not** supported for Intel XPU Docker in this project.

### 1. Host GPU drivers

On SCALE, install / enable Intel GPU userspace so Level Zero and `/dev/dri` exist on the host. Exact packages depend on SCALE version; verify:

```bash
ls -l /dev/dri
# expect card0 / renderD128 (names may vary)
```

If `/dev/dri` is missing, fix host drivers before Compose.

### 2. Dataset for project + models

Create a dataset, e.g. `tank/apps/ace-step`, and clone the repo there:

```bash
cd /mnt/tank/apps/ace-step   # adjust to your path
git clone https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker.git .
cp .env.xpu.example .env
```

Keep `./checkpoints` on the dataset so models survive container recreation.

### 3. Docker Compose

SCALE App “Custom App” / Launch Docker Compose (UI differs by SCALE version):

- Compose file: `docker-compose.xpu.yml`
- Workdir: the dataset path above
- Ensure **device** `/dev/dri` is available (compose already maps it)

Or from shell (if Docker CLI is available):

```bash
cd /mnt/tank/apps/ace-step
docker compose -f docker-compose.xpu.yml up -d --build
```

### 4. Ports / firewall

Expose or reverse-proxy:

| Port | Service |
|------|---------|
| 3003 | Web UI |
| 3004 | UI API (optional from LAN) |
| 8001 | ACE-Step API (optional; UI talks over the Docker network) |

### 5. Permissions notes

- Mounting `/var/run/docker.sock` (for the **Restart acestep-xpu** button) needs a user/group that can talk to Docker on SCALE. If restart fails with permission errors, either fix socket group membership or set `ENABLE_DOCKER_RESTART=false` and restart from the TrueNAS shell:
  `docker restart acestep-xpu`
- GPU access requires the container to see `/dev/dri` (already in compose).

### 6. Updates

```bash
cd /mnt/tank/apps/ace-step
git pull origin main
docker compose -f docker-compose.xpu.yml up -d --build
```

Do **not** use `docker compose down -v` if you want to keep the UI SQLite volume (`ui_data`).

---

## Restart acestep-xpu from the UI

After NaN latents or a stuck GPU, you can restart the XPU container without SSH.

- **Green floating button** (bottom-right): **Restart acestep-xpu**
- Requires login (JWT)
- API: `POST /api/system/restart-xpu`
- Compose mounts `/var/run/docker.sock` into `acestep-ui` and the image includes the Docker CLI

Disable if you do not want socket access:

```bash
# .env
ENABLE_DOCKER_RESTART=false
```

After restart, wait until logs show service ready (often **1–3 minutes**) before generating again.

---

## GPU settings (Arc)

Always use **`ACESTEP_LLM_BACKEND=pt`** on Intel XPU. Prefer **`acestep-v15-turbo`** + CPU offload on ≤16GB.

| VRAM | Suggested LM | Offload |
|------|--------------|---------|
| ≤6GB | none | on |
| 8GB | 0.6B | on |
| 10–12GB | 0.6B → try 1.7B | on |
| **16GB (A770)** | **1.7B** | **on** |
| 24GB+ | 1.7B or 4B | optional |

If you see **NaN / Inf latents** on XPU, try shorter duration first, restart XPU, and optionally:

```bash
ACESTEP_DTYPE=float32
# or
ACESTEP_EXTRA_ARGS=--dtype float32
```

Then: `docker compose -f docker-compose.xpu.yml up -d --force-recreate acestep-xpu`

---

## Defaults (A770 16GB)

| Setting | Value |
|---------|--------|
| DiT | `acestep-v15-turbo` |
| LM | `acestep-5Hz-lm-1.7B` |
| LM backend | `pt` |
| CPU offload | enabled |
| Mode | `gradio-api` |
| UI ports | 3003 / 3004 |

### Python packages baked into `acestep-xpu`

| Package | Notes |
|---------|--------|
| PyTorch **nightly XPU** | Forced last via `download.pytorch.org/whl/nightly/xpu` |
| **torchao ≥ 0.16** | XPU index + `--no-deps` (PEFT/training) |
| **bitsandbytes ≥ 0.48** | `--no-deps` |
| **lycoris-lora** | LoKr |
| **soundfile + ffmpeg** | Audio load / convert — **not** TorchCodec |

Do **not** install generic CUDA `torchao`/`bitsandbytes`/`torchcodec` without care — that can break `+xpu` torch or pull `libnvrtc`.

**IPEX** is not used: native PyTorch XPU is preferred (IPEX is EOL).

---

## Verified features

| Feature | Status |
|---------|--------|
| XPU generation on Arc A770 16GB | Working |
| ace-step-ui → Gradio songs | Working |
| AI Format (slow first call with offload) | Working |
| **Save dataset (local JSON)** | Working |
| **Preprocess → `.pt` (soundfile)** | Working |
| torchao ≥0.16 + bitsandbytes + lycoris in image | Baked in Dockerfile.xpu |
| Mobile-friendly UI | Better than plain Gradio |
| Per-user settings in SQLite (`ui_data`) | API ready |
| Restart XPU from UI | Optional via docker.sock |
| SSE log console (login required) | Optional |

---

## Useful commands

```bash
docker compose -f docker-compose.xpu.yml logs -f acestep-xpu
docker compose -f docker-compose.xpu.yml logs -f acestep-ui

docker compose -f docker-compose.xpu.yml up -d --build

curl -sS http://127.0.0.1:8001/health
docker restart acestep-xpu
```

---

## Key files

| File | Purpose |
|------|---------|
| `Dockerfile.xpu` | Intel packages, XPU PyTorch, torchao/bnb/lycoris/soundfile, Gradio+API |
| `Dockerfile.ui` | ace-step-ui patches (incl. local save-dataset), settings, restart, SSE |
| `docker/ui-patches/preprocess_dataset.py` | XPU LoRA preprocess helper |
| `docker/ui-patches/training-docker.py` | Training route patches (save/preprocess/init) |
| `docker-compose.xpu.yml` | Both services, `/dev/dri`, shared volumes, ports |
| `.env.xpu.example` | A770-oriented defaults |
| `README-DOCKER-XPU.md` | This document |

---

## Troubleshooting

**XPU not detected** — host drivers + `/dev/dri` in compose; PyTorch must be `+xpu`.

**NaN latents** — restart XPU; shorter duration; try `float32`; avoid bad LoRAs.

**Format spins a long time** — first 1.7B+offload Format can take 1–3 minutes.

**Save dataset Not Found** — rebuild UI so `training-docker.py` replaces `/v1/dataset/save` with local write. Image must contain `[Training] Saved dataset` and **not** `/v1/dataset/save`.

**Preprocess TorchCodec / libnvrtc** — convert to WAV; use the soundfile-patched preprocess script (do not rely on TorchCodec on XPU).

**Preprocess 0/N failed** — ensure samples are labeled, paths exist, `genre_ratio` is a number, WAVs present.

**Restart button / log console** — log in on the UI first (JWT in localStorage).

**`pull access denied` for local images** — always `up --build` (images are local).

---

## Upstream

- Model: [ace-step/ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5)
- UI: [fspecii/ace-step-ui](https://github.com/fspecii/ace-step-ui)

This repo is packaging + Arc/Docker/UI integration, not a reimplementation of the model.
