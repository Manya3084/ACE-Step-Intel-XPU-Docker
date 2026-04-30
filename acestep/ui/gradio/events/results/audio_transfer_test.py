"""Tests for result-audio transfer helpers."""

import tempfile
import unittest

from acestep.ui.gradio.events.results.audio_transfer import send_audio_to_repaint


class SendAudioToRepaintTests(unittest.TestCase):
    """Cover session-aware Send To Repaint behavior."""

    def test_send_to_repaint_sets_hidden_source_session_from_current_batch(self):
        """Generated session artifacts should be wired into hidden repaint state."""
        with tempfile.TemporaryDirectory() as session_dir:
            batch_queue = {
                0: {
                    "extra_outputs": {
                        "session_output_dir": session_dir,
                    },
                },
            }
            result = send_audio_to_repaint(
                "/tmp/sample-2.wav",
                {"lyrics": "saved lyrics", "caption": "saved caption"},
                "",
                "",
                "Custom",
                0,
                batch_queue,
                2,
            )

        repaint_mode_update = result[6 + 33]
        self.assertEqual("Repaint", result[1]["value"])
        self.assertIn("most natural", repaint_mode_update["choices"])
        self.assertEqual("auto", repaint_mode_update["value"])
        self.assertEqual(session_dir, result[-2])
        self.assertEqual(2, result[-1])

    def test_send_to_repaint_without_session_hides_most_natural_choice(self):
        """Non-session repaint should keep the ordinary repaint choices."""
        result = send_audio_to_repaint(
            "/tmp/sample.wav",
            None,
            "current lyrics",
            "current caption",
            "Custom",
            0,
            {},
            1,
        )

        repaint_mode_update = result[6 + 33]
        self.assertNotIn("most natural", repaint_mode_update["choices"])
        self.assertEqual("", result[-2])
        self.assertEqual(1, result[-1])


if __name__ == "__main__":
    unittest.main()
