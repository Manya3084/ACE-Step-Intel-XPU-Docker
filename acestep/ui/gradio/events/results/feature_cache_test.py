"""Tests for disk-backed Gradio feature cache helpers."""

import tempfile
import unittest

import torch

from acestep.ui.gradio.events.results.feature_cache import (
    FEATURE_TENSOR_KEYS,
    build_storable_extra_outputs,
    feature_duration_seconds,
    load_sample_feature_data,
    persist_feature_cache,
)


def _extra_outputs(batch_size: int = 2) -> dict[str, torch.Tensor]:
    """Build a complete feature tensor payload."""
    return {
        "pred_latents": torch.arange(batch_size * 4 * 3).reshape(batch_size, 4, 3),
        "encoder_hidden_states": torch.ones(batch_size, 2, 3),
        "encoder_attention_mask": torch.ones(batch_size, 2),
        "context_latents": torch.full((batch_size, 4, 3), 2.0),
        "lyric_token_idss": torch.ones(batch_size, 5, dtype=torch.long),
    }


class FeatureCacheTests(unittest.TestCase):
    """Cover feature persistence, loading, and queue-safe storage."""

    def test_persist_and_load_sample_feature_data(self):
        """Saved feature files should load only the requested sample."""
        extra_outputs = _extra_outputs()
        with tempfile.TemporaryDirectory() as cache_dir:
            self.assertTrue(persist_feature_cache(extra_outputs, cache_dir))
            loaded = load_sample_feature_data(extra_outputs, 1)

        self.assertIsNotNone(loaded)
        self.assertEqual(tuple(loaded["pred_latent"].shape), (1, 4, 3))
        self.assertTrue(
            torch.equal(loaded["pred_latent"], extra_outputs["pred_latents"][1:2].cpu())
        )
        self.assertEqual(feature_duration_seconds(loaded), 4 / 25.0)

    def test_storable_outputs_drop_tensors_when_cache_exists(self):
        """Batch queue storage should keep cache paths instead of large tensors."""
        extra_outputs = _extra_outputs()
        with tempfile.TemporaryDirectory() as cache_dir:
            persist_feature_cache(extra_outputs, cache_dir)
            storable = build_storable_extra_outputs(extra_outputs, ["lrc"], [None])

        for key in FEATURE_TENSOR_KEYS:
            self.assertNotIn(key, storable)
        self.assertIn("feature_cache_files", storable)
        self.assertEqual(["lrc"], storable["lrcs"])

    def test_storable_outputs_keep_tensors_without_cache(self):
        """Tensor payloads remain available when disk persistence is absent."""
        extra_outputs = _extra_outputs()
        storable = build_storable_extra_outputs(extra_outputs, [], [])

        for key in FEATURE_TENSOR_KEYS:
            self.assertIn(key, storable)


if __name__ == "__main__":
    unittest.main()
