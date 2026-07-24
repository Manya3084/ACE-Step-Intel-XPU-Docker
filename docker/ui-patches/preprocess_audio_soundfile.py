#!/usr/bin/env python3
"""Replace acestep preprocess_audio.load_audio_stereo with soundfile backend.

TorchCodec / torchaudio.load requires CUDA libs (libnvrtc) and fails on pure
Intel XPU images. soundfile + libsndfile works for wav/flac/etc.
"""
from pathlib import Path
import sys

candidates = [
    Path("/app/acestep/training/dataset_builder_modules/preprocess_audio.py"),
    Path("acestep/training/dataset_builder_modules/preprocess_audio.py"),
]
TARGET = next((p for p in candidates if p.is_file()), None)
if TARGET is None:
    print("preprocess_audio.py not found", file=sys.stderr)
    sys.exit(1)

TARGET.write_text(
    '''"""Audio loading for LoRA preprocess — soundfile backend (XPU-safe)."""
from __future__ import annotations

import torch


def load_audio_stereo(audio_path, target_sample_rate=48000, max_duration=240.0):
    """Load mono/stereo audio as float32 [2, T] at target_sample_rate."""
    import soundfile as sf

    data, sr = sf.read(str(audio_path), always_2d=True)
    audio = torch.from_numpy(data.T).float()
    if audio.shape[0] == 1:
        audio = audio.repeat(2, 1)
    elif audio.shape[0] > 2:
        audio = audio[:2]
    if int(sr) != int(target_sample_rate):
        audio = torch.nn.functional.interpolate(
            audio.unsqueeze(0),
            size=int(audio.shape[1] * target_sample_rate / sr),
            mode="linear",
            align_corners=False,
        ).squeeze(0)
        sr = target_sample_rate
    max_len = int(max_duration * sr)
    if audio.shape[1] > max_len:
        audio = audio[:, :max_len]
    return audio, int(sr)
'''
    ,
    encoding="utf-8",
)
print(f"OK wrote soundfile loader -> {TARGET}")
