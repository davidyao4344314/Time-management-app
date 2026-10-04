import unittest
from unittest.mock import Mock, patch

from backend.app.ai.context import selection
from backend.app.ai.context.adaptive import store, learning
from backend.app.ai.context.adaptive.contracts import PatternApproval
from backend.app.ai.context.adaptive.patterns import compile_patterns, pattern_id
from backend.app.ai.context.contracts import AgentIntentClassification
from backend.tests.ai.test_adaptive_patterns import evidence_rows, NOW, PROFILE
from backend.tests.ai import test_adaptive_store as fixtures
from backend.tests.ai.test_adaptive_store import EMPTY, make_event


def active_patterns():
    rows = evidence_rows()
    approval = PatternApproval(selection=PROFILE, approved_label_ids=[r["label_id"] for r in rows], shadow_reviewed=True)
    return compile_patterns(rows, now=NOW, states={pattern_id(rows[0]["event"].pattern): approval.model_dump()})


class AdaptiveActiveTests(unittest.TestCase):
    def test_reviewed_active_phrase_skips_classifier_but_shadow_does_not(self):
        for mode, expected_calls in (("active", 0), ("shadow", 1)):
            with self.subTest(mode=mode), \
                    patch.object(selection, "assess_stage_one", return_value={"selection": EMPTY, "confident": False}), \
                    patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(
                        intent="general_question", time_scope="unspecified", include_activities=False,
                        include_exams=False, confidence="high")) as classifier:
                result = selection.select_agent_context(Mock(), "Help me choose a focus", [], "test-model",
                    adaptive_snapshot={"mode": mode, "patterns": active_patterns()}, evidence={})
            self.assertEqual(classifier.call_count, expected_calls)
            self.assertEqual(result["activities_scope"], "today" if mode == "active" else None)

    def test_static_conflict_audit_and_protected_references_use_semantic_router(self):
        for confident, reason, audit in ((True, None, False), (False, None, True),
                                         (False, "depends_on_recent_conversation", False)):
            with self.subTest(confident=confident, reason=reason, audit=audit), \
                    patch.object(selection, "assess_stage_one", return_value={"selection": EMPTY, "confident": confident, "reason": reason}), \
                    patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(
                        intent="general_question", time_scope="unspecified", include_activities=False,
                        include_exams=False, confidence="high")) as classifier:
                evidence = {}
                selection.select_agent_context(Mock(), "Help me choose a focus", [], "test-model",
                    adaptive_snapshot={"mode": "active", "patterns": active_patterns(), "audit_due": audit}, evidence=evidence)
            classifier.assert_called_once()
            self.assertEqual(bool(evidence.get("audit_selected")), audit)

    def test_new_contradiction_stale_or_version_change_removes_shortcut(self):
        rows = evidence_rows(40)
        identifier = pattern_id(rows[0]["event"].pattern)
        approval = PatternApproval(selection=PROFILE, approved_label_ids=[r["label_id"] for r in rows], shadow_reviewed=True)
        states = {identifier: approval.model_dump()}
        self.assertEqual(compile_patterns(rows, now=NOW, states=states)[0]["state"], "active")
        rows[0]["label_id"] = "new-correction"
        rows[0]["label"].selection.activities_scope = None
        self.assertEqual(compile_patterns(rows, now=NOW, states=states)[0]["state"], "suspended")
        approval.router_version = "old"
        self.assertFalse(compile_patterns(evidence_rows(), now=NOW, states={identifier: approval.model_dump()})[0]["eligible"])
        self.assertFalse(compile_patterns(evidence_rows() * 2, now=NOW)[0]["confirmed_count"] > 30)


class AdaptiveActiveStorageTests(unittest.TestCase):
    setUp = fixtures.AdaptiveStoreTests.setUp

    def test_correction_persists_suspension_without_auto_reactivation(self):
        event = make_event("owner-a", self.a)
        store.record_event(self.connection, event)
        identifier = pattern_id(event["pattern"])
        store.save_pattern(self.connection, "owner-a", self.a, identifier,
                           PatternApproval(selection=PROFILE, approved_label_ids=[], shadow_reviewed=True).model_dump())
        learning.apply_reviewed_label(self.connection, "owner-a", event["event_id"], {
            "signal": "developer", "status": "confirmed", "selection": EMPTY,
            "confirmed_fields": ["activities_scope", "include_exams", "exam_scope", "memory"]})
        self.assertTrue(store.load_pattern_states(self.connection, "owner-a", self.a)[identifier]["suspended"])
        learning.apply_reviewed_label(self.connection, "owner-a", event["event_id"], {
            "signal": "developer", "status": "confirmed", "selection": PROFILE,
            "confirmed_fields": ["activities_scope", "include_exams", "exam_scope", "memory"]})
        self.assertTrue(store.load_pattern_states(self.connection, "owner-a", self.a)[identifier]["suspended"])

    def test_daily_audit_budget_is_owner_scoped_and_retry_safe(self):
        reserve = lambda chat, request: store.reserve_audit(self.connection, "owner-a", chat, request, "2026-10-04", limit=2)
        self.assertTrue(reserve(self.a, "one"))
        self.assertTrue(reserve(self.other, "two"))
        self.assertFalse(reserve(self.a, "three"))
        self.assertTrue(reserve(self.a, "one"))
        self.assertEqual(store.load_pattern_states(self.connection, "owner-a", self.a), {})
        with self.assertRaises(ValueError):
            reserve(self.b, "unauthorized")
