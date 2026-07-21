# ACE-Step 1.5 — Docker on Intel Arc / XPU (A770 etc.)

This branch adds first-class Docker support for **Intel Arc GPUs** (tested focus: **A770 16GB**).

## Files added

| File | Purpose |
|------|---------|
| `Dockerfile.xpu` | Builds the image with XPU-enabled PyTorch + Level Zero bits |
| `docker-compose.xpu.yml` | Ready-to-use Compose file for Linux / OMV |
| `README-DOCKER-XPU.md` | This guide |

## Host prerequisites (OpenMediaVault / Debian / Ubuntu)

1. **Intel Arc drivers** installed and working (`intel_gpu_top` or `clinfo` should see the A770).
2. Level Zero + OpenCL ICD packages:
   ```bash
   sudo apt update
   sudo apt install -y intel-opencl-icd intel-level-zero-gpu level-zero libze1
   ```
3. User in the `video` and `render` groups (recommended):
   ```bash
   sudo usermod -aG video,render $USER
   ```
4. Docker + Compose installed (OMV Compose plugin or Portainer is fine).

## Quick start

```bash
# Clone your fork and switch to the branch
git clone https://github.com/Manya3084/ACE-Step-1.5.git
cd ACE-Step-1.5
git checkout intel-xpu-docker

# Build and start (Gradio UI on port 7860)
docker compose -f docker-compose.xpu.yml up --build

# Or run detached
docker compose -f docker-compose.xpu.yml up -d --build
```

Open http://your-server-ip:7860

### API mode

```bash
ACESTEP_MODE=api docker compose -f docker-compose.xpu.yml up -d
```

## Recommended settings for Arc A770 16GB

The compose file defaults to:

- DiT: `acestep-v15-turbo` (fast)
- LM: `acestep-5Hz-lm-1.7B` (good balance)
- CPU offload enabled

You can override in a `.env` file or environment variables:

```env
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B   # or 4B if you want higher quality + more offload
ACESTEP_OFFLOAD_TO_CPU=true
```

## Device passthrough notes

The compose file currently passes:

```yaml
devices:
  - /dev/dri:/dev/dri
```

On most systems this is sufficient for Arc + Level Zero.  
If the container still cannot see the GPU, try also adding the render group or extra devices.

## Troubleshooting

**XPU not detected inside container**
- Confirm host sees the GPU: `clinfo` / `intel_gpu_top`
- Check `/dev/dri` is present and permissions are correct
- Restart Docker after installing Level Zero packages

**Out of memory**
- Stick with turbo + 1.7B first
- Keep `ACESTEP_OFFLOAD_TO_CPU=true`
- Close other GPU workloads

**First start is slow**
- Normal — models are downloaded / initialized on first run. Subsequent starts are much faster if you mount `./checkpoints`.

## Status

This is an initial working Docker setup targeted at the A770 16GB.  
Further tuning (better base images, multi-stage builds, oneAPI base containers, etc.) can be added later.

Feel free to open issues or PRs against the `intel-xpu-docker` branch.
