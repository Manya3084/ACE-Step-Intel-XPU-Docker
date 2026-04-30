"""Session artifact helpers for session-backed repaint retake mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch

from acestep.core.generation.handler.retake_session_save import (
    save_generation_session_artifacts,
)


MOST_NATURAL_REPAINT_MODE = "most natural"
MOST_NATURAL_SOURCE_LATENT_MIX_RATIO = 0.3
_RETAKE_MODE_ALIASES = {"retake", "most_natural", "most-natural", MOST_NATURAL_REPAINT_MODE}


def normalize_repaint_mode_alias(mode: str) -> str:
    """Normalize public repaint mode aliases to their canonical value.

    Args:
        mode: Requested repaint mode string.

    Returns:
        Canonical public repaint mode string.
    """
    requested = (mode or "auto").strip().lower()
    return MOST_NATURAL_REPAINT_MODE if requested in _RETAKE_MODE_ALIASES else requested


def is_session_retake_mode(mode: str) -> bool:
    """Return whether ``mode`` selects the session-backed retake path."""
    return normalize_repaint_mode_alias(mode) == MOST_NATURAL_REPAINT_MODE


def resolve_repaint_mode(mode: str, source_session_dir: Optional[str]) -> str:
    """Resolve repaint mode defaults for session-backed retake.

    Args:
        mode: Requested repaint mode.
        source_session_dir: Optional reusable source session directory.

    Returns:
        Effective repaint mode.
    """
    requested = normalize_repaint_mode_alias(mode)
    if requested == "auto":
        return MOST_NATURAL_REPAINT_MODE if source_session_dir else "balanced"
    return requested


def load_retake_source_track(session_dir: str, track_index: int = 1) -> dict[str, Any]:
    """Load source track artifacts required by retake repaint.

    Args:
        session_dir: Directory containing session artifacts.
        track_index: One-based track index.

    Returns:
        Mapping containing params, optional LM metadata, audio codes, and latents.

    Raises:
        FileNotFoundError: If required artifact files are missing.
        ValueError: If required audio codes or latents are unavailable.
    """
    root = Path(session_dir).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"source_session_dir does not exist: {root}")
    index = max(1, int(track_index))
    params_path = root / f"{index:02d}_params.json"
    latents_path = root / f"{index:02d}_latents.npy"
    if not params_path.exists():
        raise FileNotFoundError(f"retake source params not found: {params_path}")
    if not latents_path.exists():
        raise FileNotFoundError(f"retake source latents not found: {latents_path}")

    params = _read_json(params_path)
    lm_metadata_path = root / "lm_metadata.json"
    lm_metadata = _read_json(lm_metadata_path) if lm_metadata_path.exists() else {}
    audio_codes = str(params.get("audio_codes") or params.get("audio_code_string") or "").strip()
    if not audio_codes:
        raise ValueError("retake source track is missing saved audio_codes")
    latents_np = np.load(latents_path).astype(np.float32)
    if latents_np.ndim != 2:
        raise ValueError("retake source latents must be shaped [T, C]")

    return {
        "session_dir": str(root),
        "track_index": index,
        "params": params,
        "lm_metadata": lm_metadata,
        "audio_codes": audio_codes,
        "latents": torch.from_numpy(latents_np),
        "duration": float(latents_np.shape[0]) / 25.0,
    }


def build_retake_generation_inputs(source: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Build DiT input values from source artifacts plus caller overrides.

    Args:
        source: Loaded source track mapping.
        overrides: Caller-provided values that may override text fields.

    Returns:
        Mapping with caption, lyrics, metadata, audio codes, and duration.
    """
    params = source["params"]
    lm_metadata = source.get("lm_metadata") or {}
    return {
        "caption": _first_text(
            overrides.get("caption"),
            lm_metadata.get("caption"),
            params.get("cot_caption"),
            params.get("caption"),
        ),
        "lyrics": _first_text(
            overrides.get("lyrics"),
            params.get("cot_lyrics"),
            lm_metadata.get("lyrics"),
            params.get("lyrics"),
        ),
        "bpm": _first_value(overrides.get("bpm"), lm_metadata.get("bpm"), params.get("cot_bpm"), params.get("bpm")),
        "keyscale": _first_text(
            overrides.get("keyscale"),
            lm_metadata.get("keyscale"),
            params.get("cot_keyscale"),
            params.get("keyscale"),
        ),
        "timesignature": _first_text(
            overrides.get("timesignature"),
            lm_metadata.get("timesignature"),
            params.get("cot_timesignature"),
            params.get("timesignature"),
        ),
        "vocal_language": _first_text(
            overrides.get("vocal_language"),
            lm_metadata.get("vocal_language"),
            lm_metadata.get("language"),
            params.get("cot_vocal_language"),
            params.get("vocal_language"),
            "unknown",
        ),
        "duration": source["duration"],
        "audio_codes": source["audio_codes"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2, default=str)


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", "N/A"):
            return value
    return None


def _first_text(*values: Any) -> str:
    value = _first_value(*values)
    return "" if value is None else str(value)
