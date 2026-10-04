import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.app.ai.context.adaptive.contracts import RoutingEvent, RoutingLabel, PatternApproval
from backend.app.ai.context.adaptive.patterns import compile_patterns, match_pattern, pattern_id
from backend.app.ai.context import selection
from backend.app.ai.context.contracts import AgentIntentClassification, ContextSelection
from backend.tests.ai.test_adaptive_store import make_event, EMPTY

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
PROFILE = {**EMPTY, "activities_scope": "today"}


def evidence_rows(count=30):
    rows = []
    for index in range(count):
        event = RoutingEvent.model_validate(make_event("owner", "chat", str(index),
            pattern="help me choose a focus", request_excerpt="Help me choose a focus",
            timestamp=(NOW - timedelta(days=index % 3)).isoformat()))
        label = RoutingLabel(signal="developer", status="confirmed", selection=PROFILE,
                             confirmed_fields=["activities_scope", "include_exams", "exam_scope", "memory"])
        rows.append({"event": event, "label": label, "label_id": str(index)})
    return rows


class AdaptivePatternTests(unittest.TestCase):
    def test_memory_reviews_count_against_schedule_shortcuts(self):
        memory_profile = ContextSelection.model_validate({**EMPTY, "memory": {
            "sources": ["raw_archive"], "scope": "current_chat",
            "query": {"time_reference": "unspecified", "search_terms": ["focus"]}}})
        for schedule_count, memory_count, agreement, eligible in (
                (30, 70, 0.70, False), (97, 3, 0.97, True), (0, 30, 1.0, False)):
            with self.subTest(schedule=schedule_count, memory=memory_count):
                rows = evidence_rows(schedule_count + memory_count)
                for row in rows[schedule_count:]:
                    row["label"].selection = memory_profile
                result = compile_patterns(rows, now=NOW)[0]
                self.assertEqual(result["confirmed_count"], schedule_count + memory_count)
                self.assertEqual(result["agreement"], agreement)
                self.assertEqual(result["eligible"], eligible)
                if not eligible:
                    self.assertIsNone(match_pattern("Help me choose a focus", [result]))

    def test_new_memory_conflict_suspends_an_approved_schedule_rule(self):
        rows = evidence_rows(100)
        identifier = pattern_id(rows[0]["event"].pattern)
        approval = PatternApproval(selection=PROFILE, approved_label_ids=[row["label_id"] for row in rows], shadow_reviewed=True)
        rows[0]["label_id"] = "new-memory-correction"
        rows[0]["label"].selection = ContextSelection.model_validate({**EMPTY, "memory": {
            "sources": ["raw_archive"], "scope": "current_chat",
            "query": {"time_reference": "unspecified", "search_terms": ["focus"]}}})
        result = compile_patterns(rows, now=NOW, states={identifier: approval.model_dump()})[0]
        self.assertEqual(result["confirmed_count"], 100)
        self.assertEqual(result["agreement"], 0.99)
        self.assertEqual(result["state"], "suspended")
        self.assertFalse(result["eligible"])

    def test_only_confirmed_consistent_recent_evidence_qualifies(self):
        self.assertFalse(compile_patterns(evidence_rows(29), now=NOW)[0]["eligible"])
        self.assertTrue(compile_patterns(evidence_rows(), now=NOW)[0]["eligible"])
        rows = evidence_rows()
        rows[0]["label"] = RoutingLabel(signal="developer", status="confirmed", selection=EMPTY,
                                       confirmed_fields=["activities_scope", "include_exams", "exam_scope", "memory"])
        self.assertFalse(compile_patterns(rows, now=NOW)[0]["eligible"])
        for row in rows:
            row["label"] = None
        self.assertEqual(compile_patterns(rows, now=NOW), [])

    def test_stale_context_dependent_and_memory_profiles_do_not_shortcut(self):
        rows = evidence_rows()
        self.assertFalse(compile_patterns(rows, now=NOW + timedelta(days=31))[0]["eligible"])
        for row in rows:
            row["event"].context_dependent = True
        self.assertEqual(compile_patterns(rows, now=NOW), [])
        patterns = compile_patterns(evidence_rows(), now=NOW)
        self.assertIsNotNone(match_pattern("Help me choose a focus!", patterns))
        self.assertIsNone(match_pattern("Don't help me choose a focus", patterns))
        self.assertIsNone(match_pattern("Help me choose a focus tomorrow", patterns))

    def test_shadow_match_does_not_skip_semantic_classification(self):
        patterns = compile_patterns(evidence_rows(), now=NOW)
        evidence = {}
        with patch.object(selection, "assess_stage_one", return_value={"selection": EMPTY, "confident": False}), \
                patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(
                    intent="general_question", time_scope="unspecified", include_activities=False,
                    include_exams=False, confidence="high")) as classifier:
            result = selection.select_agent_context(Mock(), "Help me choose a focus", [], "test-model",
                adaptive_snapshot={"mode": "shadow", "patterns": patterns}, evidence=evidence)
        self.assertEqual(result, EMPTY)
        classifier.assert_called_once()
        self.assertEqual(evidence["adaptive"]["shortcut_state"], "shadow")
