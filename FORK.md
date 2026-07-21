# ACE-Step-Intel-XPU-Docker

**Repo:** https://github.com/Manya3084/ACE-Step-Intel-XPU-Docker  
(GitHub may still show `ACE-Step-1.5` until renamed in Settings.)

**Default branch:** `main` (Intel XPU Docker stack released)

**Purpose:** Run [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) on **Intel Arc GPUs** under **Linux Docker** (OpenMediaVault / headless servers), with **[ace-step-ui](https://github.com/fspecii/ace-step-ui)** as a mobile-friendly frontend.

Upstream supports XPU on Windows and ships CUDA Docker only. This project adds:

- `Dockerfile.xpu` — Level Zero, PyTorch XPU, Gradio + API
- `Dockerfile.ui` — ace-step-ui with CORS, Gradio arg fixes, ffmpeg
- `docker-compose.xpu.yml` — full stack on ports **8001** / **3003** / **3004**
- Hardened `/format_input` for AI Format on Arc + CPU offload

**Start here:** [README.md](./README.md) → [README-DOCKER-XPU.md](./README-DOCKER-XPU.md)
