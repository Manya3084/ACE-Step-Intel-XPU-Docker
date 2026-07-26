#!/usr/bin/env bash
set -e

echo "==========================================="
echo "  ACE-Step 1.5  —  Intel XPU"
echo "==========================================="
echo "Mode      : ${ACESTEP_MODE}"
echo "Python    : $(python --version 2>&1)"
echo "PyTorch   : $(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'N/A')"
echo "torchao   : $(python -c 'import torchao; print(torchao.__version__)' 2>/dev/null || echo 'N/A')"
echo "bnb       : $(python -c 'import bitsandbytes as b; print(b.__version__)' 2>/dev/null || echo 'N/A')"
echo "lycoris   : $(python -c 'import lycoris; print("ok")' 2>/dev/null || echo 'N/A')"
echo "soundfile : $(python -c 'import soundfile as s; print(s.__version__)' 2>/dev/null || echo 'N/A')"
echo "DCW       : $(python -c 'import pytorch_wavelets, pywt; print("ok")' 2>/dev/null || echo 'missing')"
echo "EXTRA     : ${ACESTEP_EXTRA_ARGS:-}"
echo "Turbo max steps: ${ACESTEP_TURBO_MAX_INFER_STEPS:-0} (0=uncapped)"

if python -c 'import torch; assert hasattr(torch, "xpu") and torch.xpu.is_available()' 2>/dev/null; then
    echo "XPU       : AVAILABLE"
    python -c '
import torch
print(f"Device count: {torch.xpu.device_count()}")
for i in range(torch.xpu.device_count()):
    print(f"  [{i}] {torch.xpu.get_device_name(i)}")
' 2>/dev/null || true
else
    echo "XPU       : NOT DETECTED"
fi
echo "==========================================="

# Safe runtime patches only (idempotent, do not touch api_routes.py)
if [ -f /app/docker/ui-patches/apg-xpu-fp64-fallback.py ]; then
  python3 /app/docker/ui-patches/apg-xpu-fp64-fallback.py || true
fi
if [ -f /app/docker/ui-patches/dcw-xpu-cpu-fallback.py ]; then
  python3 /app/docker/ui-patches/dcw-xpu-cpu-fallback.py || true
fi
# NOTE: do NOT run persist-last-model.py at runtime — it rewrites api_routes.py and has caused SyntaxErrors.

if [ -f /tmp/preprocess_dataset_xpu.py ]; then
  mkdir -p /app/datasets/_tools
  NEED_COPY=0
  if [ ! -f /app/datasets/_tools/preprocess_dataset.py ]; then NEED_COPY=1; fi
  if [ -f /app/datasets/_tools/preprocess_dataset.py ] && grep -q 'load_from_dict' /app/datasets/_tools/preprocess_dataset.py 2>/dev/null; then NEED_COPY=1; fi
  if [ -f /app/datasets/_tools/preprocess_dataset.py ] && ! grep -q 'AceStepHandler\|load_dataset' /app/datasets/_tools/preprocess_dataset.py 2>/dev/null; then NEED_COPY=1; fi
  if [ "$NEED_COPY" = "1" ]; then
    cp /tmp/preprocess_dataset_xpu.py /app/datasets/_tools/preprocess_dataset.py || true
    echo "[entrypoint] refreshed /app/datasets/_tools/preprocess_dataset.py"
  fi
fi

# Restore last DiT / LM from checkpoints volume
LAST_DIT_FILE=/app/checkpoints/.last_dit_model
LAST_LM_FILE=/app/checkpoints/.last_lm_model
if [ -f "$LAST_DIT_FILE" ]; then
  _saved_dit=$(tr -d '[:space:]' < "$LAST_DIT_FILE" || true)
  if [ -n "$_saved_dit" ]; then
    ACESTEP_CONFIG_PATH="$_saved_dit"
    echo "Restored DiT : ${ACESTEP_CONFIG_PATH} (from .last_dit_model)"
  fi
fi
if [ -f "$LAST_LM_FILE" ]; then
  _saved_lm=$(tr -d '[:space:]' < "$LAST_LM_FILE" || true)
  if [ -n "$_saved_lm" ]; then
    ACESTEP_LM_MODEL_PATH="$_saved_lm"
    echo "Restored LM  : ${ACESTEP_LM_MODEL_PATH} (from .last_lm_model)"
  fi
fi

INIT_ARGS=""
if [ "${ACESTEP_INIT_SERVICE:-true}" = "true" ]; then
    INIT_ARGS="--init_service true"
    [ -n "${ACESTEP_CONFIG_PATH:-}" ]   && INIT_ARGS="${INIT_ARGS} --config_path ${ACESTEP_CONFIG_PATH}"
    [ -n "${ACESTEP_LM_MODEL_PATH:-}" ] && INIT_ARGS="${INIT_ARGS} --init_llm true --lm_model_path ${ACESTEP_LM_MODEL_PATH}"
    echo "Auto-init    : DiT=${ACESTEP_CONFIG_PATH:-auto}  LM=${ACESTEP_LM_MODEL_PATH:-none}"
fi

OFFLOAD_ARGS=""
if [ "${ACESTEP_OFFLOAD_TO_CPU:-true}" = "true" ]; then
    OFFLOAD_ARGS="--offload_to_cpu true"
fi
if [ "${ACESTEP_OFFLOAD_DIT_TO_CPU:-true}" = "true" ]; then
    OFFLOAD_ARGS="${OFFLOAD_ARGS} --offload_dit_to_cpu true"
fi
echo "Offload     : to_cpu=${ACESTEP_OFFLOAD_TO_CPU:-true}  dit_to_cpu=${ACESTEP_OFFLOAD_DIT_TO_CPU:-true}"
echo "LM RAM      : offload=${ACESTEP_LM_OFFLOAD_TO_CPU:-true}  allow_4B=${ACESTEP_ALLOW_4B_LM:-true}  device=${ACESTEP_LM_DEVICE:-auto}"

if [ "${ACESTEP_MODE}" = "api" ]; then
    exec python -m acestep.api_server \
        --host "${ACESTEP_API_HOST:-0.0.0.0}" \
        --port "${ACESTEP_API_PORT:-8001}" \
        ${ACESTEP_EXTRA_ARGS:-}
elif [ "${ACESTEP_MODE}" = "gradio" ]; then
    exec python -m acestep.acestep_v15_pipeline \
        --server-name "${GRADIO_SERVER_NAME:-0.0.0.0}" \
        --port "${GRADIO_PORT:-7860}" \
        --backend "${ACESTEP_LLM_BACKEND:-pt}" \
        ${INIT_ARGS} ${OFFLOAD_ARGS} ${ACESTEP_EXTRA_ARGS:-}
else
    PORT="${ACESTEP_API_PORT:-8001}"
    echo "Starting Gradio + API endpoints on 0.0.0.0:${PORT} ..."
    exec python -m acestep.acestep_v15_pipeline \
        --server-name "${GRADIO_SERVER_NAME:-0.0.0.0}" \
        --port "${PORT}" \
        --backend "${ACESTEP_LLM_BACKEND:-pt}" \
        --enable-api \
        ${INIT_ARGS} ${OFFLOAD_ARGS} ${ACESTEP_EXTRA_ARGS:-}
fi
