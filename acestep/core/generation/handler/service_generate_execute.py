"""Execution helpers for service generation diffusion and output assembly."""

import random
from typing import Any, Dict, List, Optional, Tuple

import torch
from loguru import logger

from acestep.core.generation.handler.retake_latents import (
    align_retake_source_latents,
    build_retake_step_skip_timesteps,
)


class ServiceGenerateExecuteMixin:
    """Run diffusion execution for normalized service-generation requests."""

    def _unpack_service_processed_data(self, processed_data: Tuple[Any, ...]) -> Dict[str, Any]:
        """Convert batch preprocessing tuple into a keyed payload."""
        (
            keys,
            text_inputs,
            src_latents,
            target_latents,
            text_hidden_states,
            text_attention_mask,
            lyric_hidden_states,
            lyric_attention_mask,
            _audio_attention_mask,
            refer_audio_acoustic_hidden_states_packed,
            refer_audio_order_mask,
            chunk_mask,
            spans,
            is_covers,
            _audio_codes,
            lyric_token_idss,
            precomputed_lm_hints_25Hz,
            non_cover_text_hidden_states,
            non_cover_text_attention_masks,
            repaint_mask,
        ) = processed_data
        return {
            "keys": keys,
            "text_inputs": text_inputs,
            "src_latents": src_latents,
            "target_latents": target_latents,
            "text_hidden_states": text_hidden_states,
            "text_attention_mask": text_attention_mask,
            "lyric_hidden_states": lyric_hidden_states,
            "lyric_attention_mask": lyric_attention_mask,
            "refer_audio_acoustic_hidden_states_packed": refer_audio_acoustic_hidden_states_packed,
            "refer_audio_order_mask": refer_audio_order_mask,
            "chunk_mask": chunk_mask,
            "spans": spans,
            "is_covers": is_covers,
            "lyric_token_idss": lyric_token_idss,
            "precomputed_lm_hints_25Hz": precomputed_lm_hints_25Hz,
            "non_cover_text_hidden_states": non_cover_text_hidden_states,
            "non_cover_text_attention_masks": non_cover_text_attention_masks,
            "repaint_mask": repaint_mask,
        }

    def _resolve_service_seed_param(self, seed_list: Optional[List[int]]) -> Any:
        """Return model seed parameter: per-item seed list or random single seed."""
        if seed_list is not None:
            return seed_list
        return random.randint(0, 2**32 - 1)

    def _build_service_generate_kwargs(
        self,
        payload: Dict[str, Any],
        seed_param: Any,
        infer_steps: int,
        guidance_scale: float,
        audio_cover_strength: float,
        cover_noise_strength: float,
        infer_method: str,
        use_adg: bool,
        cfg_interval_start: float,
        cfg_interval_end: float,
        shift: float,
        timesteps: Optional[List[float]],
        repaint_crossfade_frames: int = 10,
        repaint_injection_ratio: float = 0.5,
        retake_source_latents: torch.Tensor = None,
        source_latent_mix_ratio: float = 0.0,
        sampler_mode: str = "euler",
        velocity_norm_threshold: float = 0.0,
        velocity_ema_factor: float = 0.0,
        dcw_enabled: bool = True,
        dcw_mode: str = "double",
        dcw_scaler: float = 0.05,
        dcw_high_scaler: float = 0.02,
        dcw_wavelet: str = "haar",
        retake_seed: Any = None,
        retake_variance: float = 0.0,
    ) -> Dict[str, Any]:
        """Build kwargs passed to model generation backends."""
        repaint_mask = payload.get("repaint_mask")
        clean_src_latents = payload.get("target_latents") if repaint_mask is not None else None
        aligned_retake_source_latents = None
        if retake_source_latents is not None:
            aligned_retake_source_latents = align_retake_source_latents(
                retake_source_latents,
                target_length=payload["src_latents"].shape[1],
                batch_size=payload["src_latents"].shape[0],
                device=payload["src_latents"].device,
                dtype=payload["src_latents"].dtype,
            )

        if aligned_retake_source_latents is not None and source_latent_mix_ratio > 0.0:
            if source_latent_mix_ratio >= 1.0:
                raise ValueError("source_latent_mix_ratio must be less than 1.0")
            retake_timesteps = build_retake_step_skip_timesteps(
                infer_steps=infer_steps,
                mix_ratio=source_latent_mix_ratio,
                shift=shift,
            )
            logger.info(
                "[retake] Biasing initial noise from saved source latents: "
                "mix_ratio={:.2f}, start_t={:.4f}, effective_steps={}",
                float(source_latent_mix_ratio),
                float(retake_timesteps[0]),
                len(retake_timesteps) - 1,
            )

        kwargs = {
            "text_hidden_states": payload["text_hidden_states"],
            "text_attention_mask": payload["text_attention_mask"],
            "lyric_hidden_states": payload["lyric_hidden_states"],
            "lyric_attention_mask": payload["lyric_attention_mask"],
            "refer_audio_acoustic_hidden_states_packed": payload["refer_audio_acoustic_hidden_states_packed"],
            "refer_audio_order_mask": payload["refer_audio_order_mask"],
            "src_latents": payload["src_latents"],
            "chunk_masks": payload["chunk_mask"],
            "is_covers": payload["is_covers"],
            "silence_latent": self.silence_latent,
            "seed": seed_param,
            "non_cover_text_hidden_states": payload["non_cover_text_hidden_states"],
            "non_cover_text_attention_mask": payload["non_cover_text_attention_masks"],
            "precomputed_lm_hints_25Hz": payload["precomputed_lm_hints_25Hz"],
            "audio_cover_strength": audio_cover_strength,
            "cover_noise_strength": cover_noise_strength,
            "infer_method": infer_method,
            "infer_steps": infer_steps,
            "diffusion_guidance_scale": guidance_scale,
            "use_adg": use_adg,
            "cfg_interval_start": cfg_interval_start,
            "cfg_interval_end": cfg_interval_end,
            "shift": shift,
            "repaint_mask": repaint_mask,
            "clean_src_latents": clean_src_latents,
            "repaint_crossfade_frames": repaint_crossfade_frames,
            "repaint_injection_ratio": repaint_injection_ratio,
            "retake_source_latents": aligned_retake_source_latents,
            "source_latent_mix_ratio": source_latent_mix_ratio,
            "sampler_mode": sampler_mode,
            "velocity_norm_threshold": velocity_norm_threshold,
            "velocity_ema_factor": velocity_ema_factor,
            "dcw_enabled": dcw_enabled,
            "dcw_mode": dcw_mode,
            "dcw_scaler": dcw_scaler,
            "dcw_high_scaler": dcw_high_scaler,
            "dcw_wavelet": dcw_wavelet,
            "retake_seed": retake_seed,
            "retake_variance": retake_variance,
        }
        if timesteps is not None:
            kwargs["timesteps"] = torch.tensor(timesteps, dtype=torch.float32, device=self.device)
        if aligned_retake_source_latents is not None and source_latent_mix_ratio > 0.0:
            kwargs["timesteps"] = torch.tensor(retake_timesteps, dtype=torch.float32, device=self.device)
            kwargs["retake_initial_noise_latents"] = aligned_retake_source_latents
            kwargs["retake_initial_noise_timestep"] = float(retake_timesteps[0])
        return kwargs

    def _generate_audio_with_optional_retake_noise(self, generate_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Run PyTorch generation with optional session-retake noise initialization."""
        source_latents = generate_kwargs.get("retake_initial_noise_latents")
        initial_timestep = generate_kwargs.get("retake_initial_noise_timestep")
        model_kwargs = dict(generate_kwargs)
        model_kwargs.pop("retake_initial_noise_latents", None)
        model_kwargs.pop("retake_initial_noise_timestep", None)
        model_kwargs.pop("retake_source_latents", None)
        model_kwargs.pop("source_latent_mix_ratio", None)
        if source_latents is None or initial_timestep is None:
            return self.model.generate_audio(**model_kwargs)

        original_prepare_noise = self.model.prepare_noise

        def prepare_retake_noise(context_latents: torch.Tensor, seed: Any = None) -> torch.Tensor:
            base_noise = original_prepare_noise(context_latents, seed)
            source = source_latents.to(device=base_noise.device, dtype=base_noise.dtype)
            if source.shape != base_noise.shape:
                source = align_retake_source_latents(
                    source,
                    target_length=base_noise.shape[1],
                    batch_size=base_noise.shape[0],
                    device=base_noise.device,
                    dtype=base_noise.dtype,
                )
            timestep = float(initial_timestep)
            return timestep * base_noise + (1.0 - timestep) * source

        self.model.prepare_noise = prepare_retake_noise
        try:
            return self.model.generate_audio(**model_kwargs)
        finally:
            self.model.prepare_noise = original_prepare_noise

    def _execute_service_generate_diffusion(
        self,
        payload: Dict[str, Any],
        generate_kwargs: Dict[str, Any],
        seed_param: Any,
        infer_method: str,
        shift: float,
        audio_cover_strength: float,
        retake_seed: Any = None,
        retake_variance: float = 0.0,
        flow_edit_ctx: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], torch.Tensor, torch.Tensor, torch.Tensor]:
        """Execute condition preparation and diffusion using MLX or PyTorch backend."""
        if flow_edit_ctx is not None and flow_edit_ctx.get("morph"):
            from .service_generate_flow_edit import dispatch_flow_edit_overlay

            return dispatch_flow_edit_overlay(
                self, payload=payload, generate_kwargs=generate_kwargs,
                seed_param=seed_param, flow_edit_ctx=flow_edit_ctx,
            )
        uses_retake_noise = generate_kwargs.get("retake_initial_noise_latents") is not None
        use_mlx_backend = self.use_mlx_dit and self.mlx_decoder is not None and not uses_retake_noise
        dit_backend = "MLX (native)" if use_mlx_backend else f"PyTorch ({self.device})"
        logger.info(f"[service_generate] Generating audio... (DiT backend: {dit_backend})")
        with torch.inference_mode():
            with self._load_model_context("model"):
                encoder_hidden_states, encoder_attention_mask, context_latents = self.model.prepare_condition(
                    text_hidden_states=payload["text_hidden_states"],
                    text_attention_mask=payload["text_attention_mask"],
                    lyric_hidden_states=payload["lyric_hidden_states"],
                    lyric_attention_mask=payload["lyric_attention_mask"],
                    refer_audio_acoustic_hidden_states_packed=payload["refer_audio_acoustic_hidden_states_packed"],
                    refer_audio_order_mask=payload["refer_audio_order_mask"],
                    hidden_states=payload["src_latents"],
                    attention_mask=torch.ones(
                        payload["src_latents"].shape[0],
                        payload["src_latents"].shape[1],
                        device=payload["src_latents"].device,
                        dtype=payload["src_latents"].dtype,
                    ),
                    silence_latent=self.silence_latent,
                    src_latents=payload["src_latents"],
                    chunk_masks=payload["chunk_mask"],
                    is_covers=payload["is_covers"],
                    precomputed_lm_hints_25Hz=payload["precomputed_lm_hints_25Hz"],
                )

                if use_mlx_backend:
                    if generate_kwargs.get("dcw_enabled") and generate_kwargs.get("dcw_wavelet", "haar") != "haar":
                        logger.info(
                            "[service_generate] DCW enabled on MLX path with "
                            "wavelet='{}'; non-Haar wavelets use the PyTorch "
                            "bridge and fall back to native Haar only if the "
                            "bridge dependencies are unavailable.",
                            generate_kwargs.get("dcw_wavelet"),
                        )
                    try:
                        enc_hs_nc, enc_am_nc, ctx_nc = None, None, None
                        if audio_cover_strength < 1.0 and payload["non_cover_text_hidden_states"] is not None:
                            non_is_covers = torch.zeros_like(payload["is_covers"])
                            sil_exp = self.silence_latent[:, :payload["src_latents"].shape[1], :].expand(
                                payload["src_latents"].shape[0], -1, -1
                            )
                            enc_hs_nc, enc_am_nc, ctx_nc = self.model.prepare_condition(
                                text_hidden_states=payload["non_cover_text_hidden_states"],
                                text_attention_mask=payload["non_cover_text_attention_masks"],
                                lyric_hidden_states=payload["lyric_hidden_states"],
                                lyric_attention_mask=payload["lyric_attention_mask"],
                                refer_audio_acoustic_hidden_states_packed=payload["refer_audio_acoustic_hidden_states_packed"],
                                refer_audio_order_mask=payload["refer_audio_order_mask"],
                                hidden_states=sil_exp,
                                attention_mask=torch.ones(
                                    sil_exp.shape[0], sil_exp.shape[1], device=sil_exp.device, dtype=sil_exp.dtype
                                ),
                                silence_latent=self.silence_latent,
                                src_latents=sil_exp,
                                chunk_masks=payload["chunk_mask"],
                                is_covers=non_is_covers,
                            )

                        null_cond_emb = getattr(self.model, "null_condition_emb", None)

                        outputs = self._mlx_run_diffusion(
                            encoder_hidden_states=encoder_hidden_states,
                            encoder_attention_mask=encoder_attention_mask,
                            context_latents=context_latents,
                            src_latents=payload["src_latents"],
                            seed=seed_param,
                            infer_method=infer_method,
                            shift=shift,
                            timesteps=generate_kwargs.get("timesteps"),
                            infer_steps=generate_kwargs.get("infer_steps"),
                            guidance_scale=generate_kwargs.get("diffusion_guidance_scale", 1.0),
                            null_condition_emb=null_cond_emb,
                            cfg_interval_start=generate_kwargs.get("cfg_interval_start", 0.0),
                            cfg_interval_end=generate_kwargs.get("cfg_interval_end", 1.0),
                            audio_cover_strength=audio_cover_strength,
                            encoder_hidden_states_non_cover=enc_hs_nc,
                            encoder_attention_mask_non_cover=enc_am_nc,
                            context_latents_non_cover=ctx_nc,
                            sampler_mode=generate_kwargs.get("sampler_mode", "euler"),
                            velocity_norm_threshold=generate_kwargs.get("velocity_norm_threshold", 0.0),
                            velocity_ema_factor=generate_kwargs.get("velocity_ema_factor", 0.0),
                            dcw_enabled=generate_kwargs.get("dcw_enabled", True),
                            dcw_mode=generate_kwargs.get("dcw_mode", "double"),
                            dcw_scaler=generate_kwargs.get("dcw_scaler", 0.05),
                            dcw_high_scaler=generate_kwargs.get("dcw_high_scaler", 0.02),
                            dcw_wavelet=generate_kwargs.get("dcw_wavelet", "haar"),
                            retake_seed=retake_seed,
                            retake_variance=retake_variance,
                        )
                        _tc = outputs.get("time_costs", {})
                        logger.info(
                            "[service_generate] DiT diffusion complete via MLX ({:.2f}s total, {:.3f}s/step).",
                            _tc.get("diffusion_time_cost", 0),
                            _tc.get("diffusion_per_step_time_cost", 0),
                        )
                    except Exception as exc:
                        logger.warning("[service_generate] MLX diffusion failed ({}); falling back to PyTorch.", exc)
                        outputs = self._generate_audio_with_optional_retake_noise(generate_kwargs)
                else:
                    logger.info("[service_generate] DiT diffusion via PyTorch ({})...", self.device)
                    outputs = self._generate_audio_with_optional_retake_noise(generate_kwargs)

        return outputs, encoder_hidden_states, encoder_attention_mask, context_latents
