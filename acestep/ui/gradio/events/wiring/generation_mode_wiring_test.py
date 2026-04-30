"""Tests for generation mode repaint UI wiring helpers."""

import tempfile
import unittest

from acestep.ui.gradio.events.wiring.generation_mode_wiring import (
    _on_source_session_dir_change,
)


class RepaintModeChoiceTests(unittest.TestCase):
    """Verify session-backed repaint mode visibility rules."""

    def test_most_natural_hidden_without_session_folder(self):
        """Most natural should not appear when no source session exists."""
        update = _on_source_session_dir_change("", "most natural")

        self.assertNotIn("most natural", update["choices"])
        self.assertEqual("auto", update["value"])

    def test_most_natural_visible_with_existing_session_folder(self):
        """Most natural should appear only after a valid session directory is set."""
        with tempfile.TemporaryDirectory() as tmp:
            update = _on_source_session_dir_change(tmp, "balanced")

        self.assertIn("most natural", update["choices"])
        self.assertEqual("balanced", update["value"])


if __name__ == "__main__":
    unittest.main()
