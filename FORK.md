# This fork (`intel-xpu-docker`)

**Purpose:** Run [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) on **Intel Arc GPUs** under **Linux Docker** (OpenMediaVault / headless servers), with **[ace-step-ui](https://github.com/fspecii/ace-step-ui)** as a mobile-friendly frontend.

Upstream supports XPU on Windows and ships CUDA Docker only. This branch adds the missing path:

- `Dockerfile.xpu` — Level Zero, PyTorch XPU, Gradio + API
- `Dockerfile.ui` — ace-step-ui with CORS, Gradio arg fixes, ffmpeg
- `docker-compose.xpu.yml` — full stack on ports **8001** / **3003** / **3004**
- Hardened `/format_input` for AI Format on Arc + CPU offload

**Start here:** [README-DOCKER-XPU.md](./README-DOCKER-XPU.md)

**Upstream docs / model:** remain in [README.md](./README.md) (ACE-Step project readme).
