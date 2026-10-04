import unittest
from unittest.mock import Mock, patch

from backend.app.ai.context.adaptive.metrics import summarize_reliability, high_confidence_reliability
from backend.app.ai.context.adaptive.examples import example_version_suffix
from backend.app.ai.context.adaptive.contracts import RoutingCandidate
from backend.app.ai.context.intent import CLASSIFIER_VERSION
from backend.app.ai.context import selection
from backend.app.ai.context.contracts import AgentIntentClassification, AgentRoutingDecision
from backend.tests.ai.test_adaptive_patterns import evidence_rows, NOW, PROFILE
from backend.tests.ai.test_adaptive_store import EMPTY


def reviewed_stage_two(count=50):
    rows = evidence_rows(count)
    for row in rows:
        event = row["event"]
        event.classifier_version = CLASSIFIER_VERSION
        event.candidates = [RoutingCandidate(stage="stage_2", status="matched", selection=PROFILE, confidence="high",
            classification=AgentRoutingDecision(intent="general_question", time_scope="today", include_activities=True, include_exams=False))]
        row["label"].classification = AgentRoutingDecision(intent="schedule_query", time_scope="today", include_activities=True, include_exams=False)
    return rows


class AdaptiveMetricTests(unittest.TestCase):
    def test_intent_confusion_does_not_count_as_context_failure(self):
        report = summarize_reliability(reviewed_stage_two(), now=NOW)
        self.assertEqual(report["buckets"][0]["observed_agreement"], 1)
        self.assertEqual(report["intent_confusions"], [{"predicted": "general_question", "confirmed": "schedule_query", "count": 50}])
        result = high_confidence_reliability(PROFILE, {"mode": "active", "calibration_enabled": True, "reliability": report},
                                            "test-model", CLASSIFIER_VERSION)
        self.assertEqual(result["status"], "accepted")

    def test_partial_reviews_score_only_reviewed_fields_not_full_confidence(self):
        rows = reviewed_stage_two()
        for row in rows:
            row["label"].confirmed_fields = ["include_exams"]
        report = summarize_reliability(rows, now=NOW)
        self.assertEqual(report["buckets"], [])
        self.assertEqual(report["field_results"], {"include_exams": {"correct": 50}})
        for row in rows:
            row["label"].status = "pending"
            row["label"].confirmed_fields = []
        self.assertEqual(summarize_reliability(rows, now=NOW)["buckets"], [])

    def test_unreliable_high_confidence_escalates_only_for_same_version_model_and_family(self):
        rows = reviewed_stage_two()
        for row in rows[:10]:
            row["label"].selection.activities_scope = "tomorrow"
        report = summarize_reliability(rows, now=NOW)
        snapshot = {"mode": "active", "patterns": [], "calibration_enabled": True, "reliability": report}
        self.assertTrue(high_confidence_reliability(PROFILE, snapshot, "test-model", CLASSIFIER_VERSION)["escalate"])
        self.assertFalse(high_confidence_reliability(PROFILE, snapshot, "other-model", CLASSIFIER_VERSION)["escalate"])
        self.assertFalse(high_confidence_reliability(PROFILE, snapshot, "test-model", "new-version")["escalate"])
        self.assertFalse(high_confidence_reliability(EMPTY, snapshot, "test-model", CLASSIFIER_VERSION)["escalate"])
        self.assertFalse(high_confidence_reliability(PROFILE, {**snapshot, "mode": "shadow"}, "test-model", CLASSIFIER_VERSION)["escalate"])
        with patch.object(selection, "assess_stage_one", return_value={"selection": EMPTY, "confident": False}), \
                patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(
                    intent="general_question", time_scope="today", include_activities=True, include_exams=False, confidence="high")), \
                patch.object(selection, "classify_stage_three", return_value=AgentRoutingDecision(
                    intent="general_question", time_scope="tomorrow", include_activities=True, include_exams=False)) as fallback:
            result = selection.select_agent_context(Mock(), "Help me focus", [], "test-model", adaptive_snapshot=snapshot)
        fallback.assert_called_once()
        self.assertEqual(result["activities_scope"], "tomorrow")
        self.assertEqual(fallback.call_args.args[-1]["reason"], "reviewed_reliability_low")

    def test_less_than_fifty_reviews_and_unconfirmed_recovery_do_not_calibrate(self):
        report = summarize_reliability(reviewed_stage_two(49), now=NOW)
        snapshot = {"mode": "active", "calibration_enabled": True, "reliability": report}
        self.assertEqual(high_confidence_reliability(PROFILE, snapshot, "test-model", CLASSIFIER_VERSION)["status"], "insufficient_evidence")
        rows = reviewed_stage_two()
        for row in rows:
            row["event"].recovery_requested = True
            row["label"] = None
        report = summarize_reliability(rows, now=NOW)
        self.assertEqual(report["buckets"], [])
        self.assertEqual(report["operational_signals"]["recovery_requests"], 50)
        self.assertNotEqual(example_version_suffix([{"request": "today"}]), example_version_suffix([{"request": "tomorrow"}]))
