"""Tests for Gradio generation-progress helper behavior."""

import unittest

from acestep.ui.gradio.events.results.generation_progress import (
    _should_persist_gradio_source_session,
)


class GradioSourceSessionPersistenceTests(unittest.TestCase):
    """Cover hidden source-session persistence gating."""

    def test_persists_text2music_when_llm_can_generate_audio_codes(self):
        """Text2music with initialized LM should persist source-session artifacts."""
        self.assertTrue(
            _should_persist_gradio_source_session(
                task_type="text2music",
                audio_codes="",
                think_enabled=True,
                lm_initialized=True,
                flow_edit_morph=False,
            )
        )

    def test_persists_text2music_with_user_audio_codes(self):
        """Provided audio codes should allow persistence without an initialized LM."""
        self.assertTrue(
            _should_persist_gradio_source_session(
                task_type="text2music",
                audio_codes="<|audio_code_1|>",
                think_enabled=False,
                lm_initialized=False,
                flow_edit_morph=False,
            )
        )

    def test_does_not_persist_repaint_or_morph_sources(self):
        """Only plain text2music outputs become Send To Repaint source sessions."""
        self.assertFalse(
            _should_persist_gradio_source_session(
                task_type="repaint",
                audio_codes="<|audio_code_1|>",
                think_enabled=True,
                lm_initialized=True,
                flow_edit_morph=False,
            )
        )
        self.assertFalse(
            _should_persist_gradio_source_session(
                task_type="text2music",
                audio_codes="",
                think_enabled=True,
                lm_initialized=True,
                flow_edit_morph=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
