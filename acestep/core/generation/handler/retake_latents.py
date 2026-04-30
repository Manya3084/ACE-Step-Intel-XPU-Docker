"""Latent helpers for session-backed repaint retake mode."""

from __future__ import annotations

from typing import Any, Optional

import torch

from acestep.core.generation.handler.repaint_step_injection import (
    apply_repaint_boundary_blend,
)


def build_retake_mask(
    *,
    target_length: int,
    sample_rate: int,
    repainting_start: Optional[float] = None,
    repainting_end: Optional[float] = None,
    repainting_regions: Optional[list[dict[str, Any]]] = None,
) -> torch.Tensor:
    """Build a boolean edit mask in latent-frame space.

    Args:
        target_length: Number of 25Hz latent frames.
        sample_rate: Audio sample rate used by the handler.
        repainting_start: Single-region start time in seconds.
        repainting_end: Single-region end time in seconds.
        repainting_regions: Optional list of ``{"start": x, "end": y}`` regions.

    Returns:
        Boolean tensor shaped ``[1, target_length]`` where ``True`` marks edit
        frames.

    Raises:
        ValueError: If no valid repaint region is provided.
    """
    mask = torch.zeros(1, target_length, dtype=torch.bool)
    regions = repainting_regions or [{"start": repainting_start, "end": repainting_end}]
    valid_region_count = 0
    frames_per_second = sample_rate / 1920.0

    for region in regions:
        start = 0.0 if region.get("start") is None else float(region.get("start"))
        raw_end = region.get("end")
        end = target_length / frames_per_second if raw_end is None else float(raw_end)
        if end < 0:
            end = target_length / frames_per_second
        if end <= start:
            continue
        start_frame = max(0, min(int(start * frames_per_second), target_length - 1))
        end_frame = max(start_frame + 1, min(int(end * frames_per_second), target_length))
        mask[0, start_frame:end_frame] = True
        valid_region_count += 1

    if valid_region_count == 0:
        raise ValueError("retake repaint requires at least one valid repaint region")
    return mask


def align_retake_source_latents(
    source_latents: torch.Tensor,
    *,
    target_length: int,
    batch_size: int,
    device: torch.device,
    dtype: torch.dtype,
) -> torch.Tensor:
    """Align saved source latents to a generated latent batch shape.

    Args:
        source_latents: Saved source final latents, shaped ``[T, C]`` or
            ``[B, T, C]``.
        target_length: Target latent frame count.
        batch_size: Desired batch size.
        device: Target tensor device.
        dtype: Target tensor dtype.

    Returns:
        Tensor shaped ``[batch_size, target_length, C]``.
    """
    latents = source_latents
    if latents.ndim == 2:
        latents = latents.unsqueeze(0)
    if latents.ndim != 3:
        raise ValueError("source_latents must be shaped [T, C] or [B, T, C]")
    latents = latents.to(device=device, dtype=dtype)
    if latents.shape[1] > target_length:
        latents = latents[:, :target_length, :]
    elif latents.shape[1] < target_length:
        pad = latents[:, -1:, :].expand(latents.shape[0], target_length - latents.shape[1], -1)
        latents = torch.cat([latents, pad], dim=1)
    if latents.shape[0] == 1 and batch_size > 1:
        latents = latents.expand(batch_size, -1, -1).clone()
    elif latents.shape[0] != batch_size:
        latents = latents[:1].expand(batch_size, -1, -1).clone()
    return latents


def splice_retake_latents(
    *,
    pred_latents: torch.Tensor,
    source_latents: torch.Tensor,
    repaint_mask: torch.Tensor,
    crossfade_frames: int,
) -> torch.Tensor:
    """Restore non-edit regions from saved source latents.

    Args:
        pred_latents: Generated latents shaped ``[B, T, C]``.
        source_latents: Saved source final latents.
        repaint_mask: Boolean mask shaped ``[B, T]`` or ``[1, T]``.
        crossfade_frames: Boundary crossfade width in latent frames.

    Returns:
        Spliced latents where edit frames come from ``pred_latents`` and
        non-edit frames come from source latents.
    """
    source = align_retake_source_latents(
        source_latents,
        target_length=pred_latents.shape[1],
        batch_size=pred_latents.shape[0],
        device=pred_latents.device,
        dtype=pred_latents.dtype,
    )
    mask = repaint_mask.to(device=pred_latents.device, dtype=torch.bool)
    if mask.ndim != 2:
        raise ValueError("repaint_mask must be a 2D tensor")
    if mask.shape[0] == 1 and pred_latents.shape[0] > 1:
        mask = mask.expand(pred_latents.shape[0], -1).clone()
    if mask.shape != pred_latents.shape[:2]:
        raise ValueError("repaint_mask shape must match pred_latents [B, T]")
    if crossfade_frames > 0:
        return apply_repaint_boundary_blend(pred_latents, source, mask, crossfade_frames)
    return torch.where(mask.unsqueeze(-1), pred_latents, source)


def build_retake_step_skip_timesteps(
    *,
    infer_steps: int,
    mix_ratio: float,
    shift: float,
) -> Optional[list[float]]:
    """Return a truncated timestep schedule for source-latent-biased noise.

    Args:
        infer_steps: Original diffusion step count.
        mix_ratio: Source latent mix ratio in ``[0, 1)``.
        shift: Timestep shift factor.

    Returns:
        Truncated timestep list, or ``None`` when no skip is needed.
    """
    ratio = float(mix_ratio)
    if ratio <= 0.0:
        return None
    if ratio >= 1.0:
        raise ValueError("source_latent_mix_ratio must be less than 1.0")
    if infer_steps < 1:
        raise ValueError("infer_steps must be greater than zero")
    full = [1.0 - (index / infer_steps) for index in range(infer_steps + 1)]
    if shift != 1.0:
        full = [float(shift * value / (1.0 + (shift - 1.0) * value)) for value in full]
    target_noise_level = 1.0 - ratio
    candidates = full[:-1]
    nearest = min(candidates, key=lambda value: abs(value - target_noise_level))
    return full[candidates.index(nearest):]
