import unittest
from backend.tests.ai import test_adaptive_store as fixtures
from backend.app.ai.context.adaptive import store
from backend.app.ai.context.adaptive.learning import apply_reviewed_label


EMPTY = fixtures.EMPTY
make_event = fixtures.make_event


class AdaptiveLabelTests(unittest.TestCase):
    setUp = fixtures.AdaptiveStoreTests.setUp
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
