"""Disk-backed feature cache for Gradio score and LRC helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import torch


FEATURE_TENSOR_KEYS = (
    "pred_latents",
    "encoder_hidden_states",
    "encoder_attention_mask",
    "context_latents",
    "lyric_token_idss",
)

FEATURE_CACHE_FILES_KEY = "feature_cache_files"
FEATURE_CACHE_DIR_KEY = "feature_cache_dir"


def persist_feature_cache(extra_outputs: dict[str, Any], cache_dir: str) -> bool:
    """Persist per-sample alignment features and record file paths.

    Args:
        extra_outputs: Generation extra outputs containing batch tensors.
        cache_dir: Directory where per-sample feature files should be written.

    Returns:
        ``True`` when feature files were written, otherwise ``False``.
    """
    tensors = _feature_tensors(extra_outputs)
    if tensors is None:
        return False
    batch_size = tensors["pred_latents"].shape[0]
    root = Path(cache_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for index in range(batch_size):
        path = root / f"{index + 1:02d}_features.pt"
        torch.save(_slice_sample_features(tensors, index), path)
        files.append(str(path))
    extra_outputs[FEATURE_CACHE_DIR_KEY] = str(root)
    extra_outputs[FEATURE_CACHE_FILES_KEY] = files
    return True


def build_storable_extra_outputs(
    extra_outputs: dict[str, Any],
    lrcs: list[str],
    subtitles: list[Any],
) -> dict[str, Any]:
    """Build queue-safe extra outputs, dropping cached tensors when possible.

    Args:
        extra_outputs: Generation extra outputs.
        lrcs: LRC strings to keep in batch history.
        subtitles: Subtitle file paths to keep in batch history.

    Returns:
        A shallow copy suitable for storing in the Gradio batch queue.
    """
    storable = {**(extra_outputs or {}), "lrcs": lrcs, "subtitles": subtitles}
    if storable.get(FEATURE_CACHE_FILES_KEY):
        for key in FEATURE_TENSOR_KEYS:
            storable.pop(key, None)
    return storable


def load_sample_feature_data(
    extra_outputs: dict[str, Any],
    sample_idx: int,
) -> dict[str, Any] | None:
    """Load one sample's score/LRC feature tensors from memory or disk.

    Args:
        extra_outputs: Batch extra outputs from the current result or queue.
        sample_idx: Zero-based sample index.

    Returns:
        Feature dictionary using score/LRC argument names, or ``None``.
    """
    tensors = _feature_tensors(extra_outputs)
    if tensors is not None and 0 <= sample_idx < tensors["pred_latents"].shape[0]:
        return _to_feature_data(_slice_sample_features(tensors, sample_idx))

    files = (extra_outputs or {}).get(FEATURE_CACHE_FILES_KEY) or []
    if not 0 <= sample_idx < len(files):
        return None
    path = str(files[sample_idx] or "")
    if not path or not os.path.exists(os.path.expanduser(path)):
        return None
    sample = _torch_load_cpu(path)
    return _to_feature_data(sample) if _feature_tensors(sample) is not None else None


def feature_duration_seconds(feature_data: dict[str, Any]) -> float | None:
    """Return duration inferred from a sample feature dictionary."""
    pred_latent = feature_data.get("pred_latent") if feature_data else None
    if pred_latent is None:
        return None
    return float(pred_latent.shape[1]) / 25.0


def _feature_tensors(values: dict[str, Any] | None) -> dict[str, torch.Tensor] | None:
    """Return required feature tensors if all are present."""
    if not isinstance(values, dict):
        return None
    tensors = {key: values.get(key) for key in FEATURE_TENSOR_KEYS}
    if any(not isinstance(value, torch.Tensor) for value in tensors.values()):
        return None
    return tensors


def _slice_sample_features(
    tensors: dict[str, torch.Tensor],
    sample_idx: int,
) -> dict[str, torch.Tensor]:
    """Slice and CPU-offload one sample from a batch feature tensor dict."""
    return {
        key: value[sample_idx:sample_idx + 1].detach().cpu()
        for key, value in tensors.items()
    }


def _to_feature_data(sample: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Map stored feature keys to score/LRC helper argument names."""
    return {
        "pred_latent": sample["pred_latents"],
        "encoder_hidden_states": sample["encoder_hidden_states"],
        "encoder_attention_mask": sample["encoder_attention_mask"],
        "context_latents": sample["context_latents"],
        "lyric_token_ids": sample["lyric_token_idss"],
    }


def _torch_load_cpu(path: str) -> dict[str, torch.Tensor]:
    """Load a feature file on CPU across supported PyTorch versions."""
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(path, map_location="cpu")
