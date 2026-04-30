"""Tests for Gradio scoring helpers."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from acestep.ui.gradio.events.results.feature_cache_test import _extra_outputs
from acestep.ui.gradio.events.results.feature_cache import (
    build_storable_extra_outputs,
    persist_feature_cache,
)
from acestep.ui.gradio.events.results.scoring import calculate_score_handler_with_selection


class CalculateScoreWithSelectionTests(unittest.TestCase):
    """Cover score calculation from disk-backed feature cache."""

    def test_loads_feature_cache_for_alignment_score(self):
        """Manual score should load per-sample tensors from cache paths."""
        extra_outputs = _extra_outputs()
        with tempfile.TemporaryDirectory() as cache_dir:
            persist_feature_cache(extra_outputs, cache_dir)
            storable = build_storable_extra_outputs(extra_outputs, [], [])
            batch_queue = {
                0: {
                    "generation_params": {"lyrics": "hello", "inference_steps": 8},
                    "extra_outputs": storable,
                    "codes": "",
                    "allow_lm_batch": False,
                    "lm_generated_metadata": {},
                }
            }

            with patch(
                "acestep.ui.gradio.events.results.scoring.calculate_score_handler",
                return_value="score-ok",
            ) as handler:
                result = calculate_score_handler_with_selection(
                    MagicMock(),
                    MagicMock(),
                    2,
                    0.5,
                    0,
                    batch_queue,
                )

        self.assertEqual("score-ok", result[0]["value"])
        extra_tensor_data = handler.call_args.args[12]
        self.assertEqual(tuple(extra_tensor_data["pred_latent"].shape), (1, 4, 3))


if __name__ == "__main__":
    unittest.main()
