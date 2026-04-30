"""Unit tests for release-task request model defaults and compatibility flags."""

import unittest

from acestep.api.http.release_task_models import GenerateMusicRequest
from acestep.constants import DEFAULT_DIT_INSTRUCTION


class ReleaseTaskModelsTests(unittest.TestCase):
    """Behavior tests for release-task request model schema defaults."""

    def test_generate_music_request_preserves_legacy_defaults(self):
        """Model should expose same default values used by existing clients."""

        req = GenerateMusicRequest()
        self.assertEqual("", req.prompt)
        self.assertEqual("text2music", req.task_type)
        self.assertEqual("mp3", req.audio_format)
        self.assertEqual(DEFAULT_DIT_INSTRUCTION, req.instruction)
        self.assertTrue(req.use_random_seed)
        self.assertEqual("auto", req.repaint_mode)

    def test_new_fields_have_expected_defaults(self):
        """New audio_code_string and cover_noise_strength should default to safe values."""

        req = GenerateMusicRequest()
        self.assertEqual("", req.audio_code_string)
        self.assertAlmostEqual(0.0, req.cover_noise_strength)
        self.assertIsNone(req.source_session_dir)
        self.assertEqual(1, req.source_track_index)
        self.assertAlmostEqual(0.3, req.source_latent_mix_ratio)

    def test_audio_code_string_and_cover_noise_strength_are_accepted(self):
        """Model should accept user-supplied audio_code_string and cover_noise_strength."""

        req = GenerateMusicRequest(
            audio_code_string="<|audio_code_1|>",
            cover_noise_strength=0.75,
            repaint_mode="most natural",
            source_session_dir="/tmp/source-session",
        )
        self.assertEqual("<|audio_code_1|>", req.audio_code_string)
        self.assertAlmostEqual(0.75, req.cover_noise_strength)
        self.assertEqual("most natural", req.repaint_mode)
        self.assertEqual("/tmp/source-session", req.source_session_dir)

    def test_legacy_retake_mode_alias_normalizes_to_most_natural(self):
        """Legacy retake API clients should keep working with the new label."""

        req = GenerateMusicRequest(repaint_mode="retake")

        self.assertEqual("most natural", req.repaint_mode)


if __name__ == "__main__":
    unittest.main()
