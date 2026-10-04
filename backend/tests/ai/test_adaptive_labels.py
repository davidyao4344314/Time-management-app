import unittest
from backend.tests.ai import test_adaptive_store as fixtures
from backend.app.ai.context.adaptive import store
from backend.app.ai.context.adaptive.learning import apply_reviewed_label
from backend.app.ai.context.adaptive.contracts import PatternApproval
from backend.app.ai.context.adaptive.patterns import pattern_id


EMPTY = fixtures.EMPTY
make_event = fixtures.make_event


class AdaptiveLabelTests(unittest.TestCase):
    setUp = fixtures.AdaptiveStoreTests.setUp

    def test_corrections_and_rejections_follow_source_chat_sharing(self):
        profile = {**EMPTY, "activities_scope": "today"}
        # Sharing the receiving chat must not grant access to a private source chat.
        fixtures.storage.set_memory_sharing(self.connection, self.a, "owner-a", True)
        for source_mode in ("private", "shared", "revoked"):
            for status in ("confirmed", "rejected"):
                with self.subTest(source=source_mode, status=status):
                    fixtures.storage.set_memory_sharing(self.connection, self.other, "owner-a", source_mode != "private")
                    if source_mode == "revoked":
                        fixtures.storage.set_memory_sharing(self.connection, self.other, "owner-a", False)
                    event = make_event("owner-a", self.other, request=source_mode + status)
                    store.record_event(self.connection, event)
                    identifier = pattern_id(event["pattern"])
                    approval = PatternApproval(selection=profile, approved_label_ids=[], shadow_reviewed=True).model_dump()
                    for owner, chat in (("owner-a", self.a), ("owner-a", self.other), ("owner-b", self.b)):
                        store.save_pattern(self.connection, owner, chat, identifier, approval)
                    label = {"signal": "developer", "status": status, "selection": EMPTY}
                    if status == "confirmed":
                        label["confirmed_fields"] = ["activities_scope", "include_exams", "exam_scope", "memory"]
                    apply_reviewed_label(self.connection, "owner-a", event["event_id"], label)
                    self.assertTrue(store.load_pattern_states(self.connection, "owner-a", self.other)[identifier]["suspended"])
                    self.assertEqual(store.load_pattern_states(self.connection, "owner-a", self.a)[identifier]["suspended"],
                                     source_mode == "shared")
                    self.assertFalse(store.load_pattern_states(self.connection, "owner-b", self.b)[identifier]["suspended"])

    def test_reviewed_classification_must_agree_with_selection(self):
        event = make_event("owner-a", self.a)
        store.record_event(self.connection, event)
        classification = {"intent": "general_question", "time_scope": "unspecified",
                          "include_activities": False, "include_exams": False}
        label = {"signal": "developer", "status": "confirmed", "selection": EMPTY,
                 "confirmed_fields": ["activities_scope", "include_exams", "exam_scope", "memory"],
                 "classification": classification, "example_approved": True}
        apply_reviewed_label(self.connection, "owner-a", event["event_id"], label)
        self.assertTrue(store.load_eligible_evidence(self.connection, "owner-a", self.a)[0]["label"].complete)
        classification["include_activities"] = True
        with self.assertRaises(ValueError):
            apply_reviewed_label(self.connection, "owner-a", event["event_id"], label)

    def test_exclusions_and_self_contained_requirement_survive_review(self):
        event = make_event("owner-a", self.a, excluded_sources=["activities"], context_dependent=True)
        store.record_event(self.connection, event)
        label = {"signal": "user_structured", "status": "confirmed",
                 "selection": {**EMPTY, "activities_scope": "tomorrow"}, "confirmed_fields": ["activities_scope"]}
        with self.assertRaises(ValueError):
            apply_reviewed_label(self.connection, "owner-a", event["event_id"], label)
        label.update(selection=EMPTY, confirmed_fields=["activities_scope", "include_exams", "exam_scope", "memory"],
                     classification={"intent": "general_question", "time_scope": "unspecified",
                                     "include_activities": False, "include_exams": False}, example_approved=True)
        with self.assertRaises(ValueError):
            apply_reviewed_label(self.connection, "owner-a", event["event_id"], label)
