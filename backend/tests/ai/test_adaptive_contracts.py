import unittest
from unittest.mock import patch
from backend.app.ai.context.adaptive.contracts import RoutingLabel
from backend.app.ai.context.adaptive.settings import get_adaptive_settings

EMPTY = {"activities_scope": None, "include_exams": False, "exam_scope": None}


class AdaptiveContractTests(unittest.TestCase):
    def test_model_disagreement_cannot_confirm_itself(self):
        for signal in ("stage3_disagreement", "context_recovery"):
            with self.assertRaises(ValueError):
                RoutingLabel(signal=signal, status="confirmed", selection=EMPTY,
                             confirmed_fields=["activities_scope"])

    def test_partial_review_is_not_a_complete_training_example(self):
        label = RoutingLabel(signal="developer", status="confirmed", selection=EMPTY,
                             confirmed_fields=["activities_scope"])
        self.assertFalse(label.complete)
        with self.assertRaises(ValueError):
            RoutingLabel(signal="developer", status="confirmed", selection=EMPTY,
                         confirmed_fields=["activities_scope"], example_approved=True)

    def test_disabled_by_default_and_invalid_settings_fail_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_adaptive_settings().mode, "off")
        with patch.dict("os.environ", {"AI_ADAPTIVE_ROUTING_MODE": "invalid"}):
            self.assertEqual(get_adaptive_settings().mode, "off")


if __name__ == "__main__":
    unittest.main()
