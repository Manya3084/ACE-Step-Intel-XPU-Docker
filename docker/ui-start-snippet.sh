#!/usr/bin/env bash
# Sourced conceptually by docker-start-ui — kept as reference for path layout.
# Compose mounts:
#   ./datasets    -> /app/datasets
#   ./lora_output -> /app/lora_output
#   ./checkpoints -> /app/checkpoints

mkdir -p /app/datasets/uploads \
         /app/datasets/preprocessed_tensors \
         /app/lora_output/checkpoints \
         /app/lora_output/final \
         /app/ACE-Step-1.5 \
         /app/server

# Compatibility for code that still hardcodes ACE-Step-1.5/datasets
if [ -d /app/datasets ]; then
  ln -sfn /app/datasets /app/ACE-Step-1.5/datasets
fi
if [ -d /app/checkpoints ]; then
  ln -sfn /app/checkpoints /app/ACE-Step-1.5/checkpoints
fi
if [ -d /app/lora_output ]; then
  ln -sfn /app/lora_output /app/server/lora_output
  ln -sfn /app/lora_output /app/lora_output
fi
