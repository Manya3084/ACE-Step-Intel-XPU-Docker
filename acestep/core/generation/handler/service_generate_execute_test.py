"""Unit tests for service-generation execution helper mixin."""

import unittest
from unittest.mock import patch

import torch

from acestep.core.generation.handler.service_generate_execute import ServiceGenerateExecuteMixin
from acestep.core.generation.handler.service_generate_outputs import ServiceGenerateOutputsMixin


class _Host(ServiceGenerateExecuteMixin, ServiceGenerateOutputsMixin):
    """Test host exposing the minimum attributes used by execute helpers."""

    def __init__(self):
        """Initialize static runtime fields for helper-method tests."""
        self.device = "cpu"
        self.silence_latent = torch.zeros(1, 4, 4, dtype=torch.float32)


class ServiceGenerateExecuteMixinTests(unittest.TestCase):
    """Validate helper behavior for kwargs and output assembly."""

    def test_build_generate_kwargs_adds_timesteps_tensor(self):
        """Timesteps input should be converted to a device tensor in kwargs."""
        host = _Host()
        payload = {
            "text_hidden_states": torch.zeros(1, 2),
            "text_attention_mask": torch.ones(1, 2),
            "lyric_hidden_states": torch.zeros(1, 2),
            "lyric_attention_mask": torch.ones(1, 2),
            "refer_audio_acoustic_hidden_states_packed": torch.zeros(1, 2),
            "refer_audio_order_mask": torch.zeros(1, dtype=torch.long),
            "src_latents": torch.zeros(1, 4, 4),
            "chunk_mask": torch.ones(1, 4, dtype=torch.bool),
            "is_covers": torch.tensor([True]),
            "non_cover_text_hidden_states": None,
            "non_cover_text_attention_masks": None,
            "precomputed_lm_hints_25Hz": None,
        }
        kwargs = host._build_service_generate_kwargs(
            payload=payload,
            seed_param=123,
            infer_steps=16,
            guidance_scale=7.0,
            audio_cover_strength=1.0,
            cover_noise_strength=0.0,
            infer_method="ode",
            use_adg=False,
            cfg_interval_start=0.0,
            cfg_interval_end=1.0,
            shift=1.0,
            timesteps=[1.0, 0.5],
        )

        self.assertIn("timesteps", kwargs)
        self.assertEqual(kwargs["seed"], 123)
        self.assertEqual(kwargs["infer_steps"], 16)
        self.assertEqual(kwargs["timesteps"].dtype, torch.float32)
        self.assertEqual(kwargs["timesteps"].device.type, "cpu")

    def test_build_generate_kwargs_uses_retake_source_latents_for_noise_mix(self):
        """Session retake mix should use saved source latents for noise initialization."""
        host = _Host()
        payload = {
            "text_hidden_states": torch.zeros(1, 2),
            "text_attention_mask": torch.ones(1, 2),
            "lyric_hidden_states": torch.zeros(1, 2),
            "lyric_attention_mask": torch.ones(1, 2),
            "refer_audio_acoustic_hidden_states_packed": torch.zeros(1, 2),
            "refer_audio_order_mask": torch.zeros(1, dtype=torch.long),
            "src_latents": torch.zeros(1, 4, 4),
            "chunk_mask": torch.ones(1, 4, dtype=torch.bool),
            "is_covers": torch.tensor([True]),
            "non_cover_text_hidden_states": None,
            "non_cover_text_attention_masks": None,
            "precomputed_lm_hints_25Hz": None,
        }
        source_latents = torch.ones(4, 4)

        kwargs = host._build_service_generate_kwargs(
            payload=payload,
            seed_param=123,
            infer_steps=16,
            guidance_scale=7.0,
            audio_cover_strength=1.0,
            cover_noise_strength=0.0,
            infer_method="ode",
            use_adg=False,
            cfg_interval_start=0.0,
            cfg_interval_end=1.0,
            shift=1.0,
            timesteps=None,
            retake_source_latents=source_latents,
            source_latent_mix_ratio=0.3,
        )

        torch.testing.assert_close(kwargs["src_latents"], torch.zeros(1, 4, 4))
        torch.testing.assert_close(kwargs["retake_source_latents"], torch.ones(1, 4, 4))
        self.assertEqual(kwargs["cover_noise_strength"], 0.0)
        self.assertIn("retake_initial_noise_latents", kwargs)
        self.assertAlmostEqual(float(kwargs["timesteps"][0]), 0.6875)
        self.assertEqual(kwargs["timesteps"].numel(), 12)

    def test_build_generate_kwargs_rejects_full_retake_source_mix(self):
        """Retake source mix must leave some noise for the diffusion schedule."""
        host = _Host()
        payload = {
            "text_hidden_states": torch.zeros(1, 2),
            "text_attention_mask": torch.ones(1, 2),
            "lyric_hidden_states": torch.zeros(1, 2),
            "lyric_attention_mask": torch.ones(1, 2),
            "refer_audio_acoustic_hidden_states_packed": torch.zeros(1, 2),
            "refer_audio_order_mask": torch.zeros(1, dtype=torch.long),
            "src_latents": torch.zeros(1, 4, 4),
            "chunk_mask": torch.ones(1, 4, dtype=torch.bool),
            "is_covers": torch.tensor([True]),
            "non_cover_text_hidden_states": None,
            "non_cover_text_attention_masks": None,
            "precomputed_lm_hints_25Hz": None,
        }

        with self.assertRaisesRegex(ValueError, "source_latent_mix_ratio"):
            host._build_service_generate_kwargs(
                payload=payload,
                seed_param=123,
                infer_steps=16,
                guidance_scale=7.0,
                audio_cover_strength=1.0,
                cover_noise_strength=0.0,
                infer_method="ode",
                use_adg=False,
                cfg_interval_start=0.0,
                cfg_interval_end=1.0,
                shift=1.0,
                timesteps=None,
                retake_source_latents=torch.ones(4, 4),
                source_latent_mix_ratio=1.0,
            )

    def test_generate_audio_with_optional_retake_noise_mixes_prepare_noise(self):
        """Retake noise patch should restore the model method after generation."""
        host = _Host()

        class _Model:
            def __init__(self):
                self.restored_prepare_noise = None

            def prepare_noise(self, context_latents, seed=None):
                return torch.ones_like(context_latents)

            def generate_audio(self, **kwargs):
                self.seen_kwargs = kwargs
                context = torch.zeros(1, 2, 2)
                mixed_noise = self.prepare_noise(context, seed=kwargs["seed"])
                return {"target_latents": mixed_noise}

        model = _Model()
        host.model = model
        original_prepare_noise = model.prepare_noise

        outputs = host._generate_audio_with_optional_retake_noise(
            {
                "seed": 123,
                "retake_source_latents": torch.ones(1, 2, 2) * 9.0,
                "source_latent_mix_ratio": 0.3,
                "retake_initial_noise_latents": torch.ones(1, 2, 2) * 3.0,
                "retake_initial_noise_timestep": 0.25,
            }
        )

        torch.testing.assert_close(outputs["target_latents"], torch.ones(1, 2, 2) * 2.5)
        self.assertNotIn("retake_source_latents", model.seen_kwargs)
        self.assertNotIn("source_latent_mix_ratio", model.seen_kwargs)
        self.assertEqual(model.prepare_noise.__func__, original_prepare_noise.__func__)

    def test_attach_service_outputs_persists_required_fields(self):
        """Attached payload fields should be available to downstream handlers."""
        host = _Host()
        payload = {
            "src_latents": torch.zeros(1, 4, 4),
            "target_latents": torch.ones(1, 4, 4),
            "chunk_mask": torch.ones(1, 4, dtype=torch.bool),
            "spans": [("full", 0, 4)],
            "lyric_token_idss": torch.ones(1, 3, dtype=torch.long),
        }
        outputs = host._attach_service_generate_outputs(
            outputs={"target_latents": torch.zeros(1, 4, 4)},
            payload=payload,
            batch={"latent_masks": torch.ones(1, 4, dtype=torch.long)},
            encoder_hidden_states=torch.zeros(1, 2),
            encoder_attention_mask=torch.ones(1, 2),
            context_latents=torch.zeros(1, 2),
        )

        self.assertIn("src_latents", outputs)
        self.assertIn("target_latents_input", outputs)
        self.assertIn("latent_masks", outputs)
        self.assertIn("encoder_hidden_states", outputs)
        self.assertIn("lyric_token_idss", outputs)

    def test_resolve_seed_param_none_uses_random_seed(self):
        """None seed list should produce a random integer seed parameter."""
        host = _Host()
        with patch("acestep.core.generation.handler.service_generate_execute.random.randint", return_value=42):
            seed_param = host._resolve_service_seed_param(None)
        self.assertEqual(seed_param, 42)


if __name__ == "__main__":
    unittest.main()
