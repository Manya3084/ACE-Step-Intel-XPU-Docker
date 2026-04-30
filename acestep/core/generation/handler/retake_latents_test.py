"""Tests for session-backed retake latent helpers."""

import unittest

import torch

from acestep.core.generation.handler.retake_latents import (
    align_retake_source_latents,
    build_retake_mask,
    build_retake_step_skip_timesteps,
    splice_retake_latents,
)


class RetakeLatentHelperTests(unittest.TestCase):
    """Verify retake mask, splice, and source-latent alignment behavior."""

    def test_build_retake_mask_supports_multiple_regions(self):
        """Multiple repaint regions should be represented in one edit mask."""
        mask = build_retake_mask(
            target_length=100,
            sample_rate=48000,
            repainting_regions=[{"start": 1.0, "end": 1.5}, {"start": 3.0, "end": 3.5}],
        )

        self.assertTrue(mask[0, 25:37].any())
        self.assertTrue(mask[0, 75:87].any())
        self.assertFalse(mask[0, :20].any())

    def test_splice_preserves_edit_and_restores_outside(self):
        """Edit frames come from generated latents; outside frames come from source."""
        pred = torch.ones(1, 8, 2) * 9.0
        source = torch.ones(1, 8, 2) * 2.0
        mask = torch.zeros(1, 8, dtype=torch.bool)
        mask[0, 3:5] = True

        result = splice_retake_latents(
            pred_latents=pred,
            source_latents=source,
            repaint_mask=mask,
            crossfade_frames=0,
        )

        torch.testing.assert_close(result[0, :3], source[0, :3])
        torch.testing.assert_close(result[0, 3:5], pred[0, 3:5])
        torch.testing.assert_close(result[0, 5:], source[0, 5:])

    def test_align_retake_source_latents_expands_single_track_to_batch(self):
        """A single saved source track should expand to generated batch size."""
        source = torch.arange(12, dtype=torch.float32).reshape(6, 2)

        aligned = align_retake_source_latents(
            source,
            target_length=4,
            batch_size=2,
            device=torch.device("cpu"),
            dtype=torch.float32,
        )

        self.assertEqual((2, 4, 2), tuple(aligned.shape))
        torch.testing.assert_close(aligned[0], source[:4])
        torch.testing.assert_close(aligned[1], source[:4])

    def test_step_skip_schedule_truncates_prefix_for_mix_ratio(self):
        """Positive source mix should remove early high-noise timesteps."""
        timesteps = build_retake_step_skip_timesteps(infer_steps=10, mix_ratio=0.3, shift=1.0)

        self.assertIsNotNone(timesteps)
        self.assertLess(len(timesteps), 11)
        self.assertAlmostEqual(timesteps[0], 0.7)


if __name__ == "__main__":
    unittest.main()
