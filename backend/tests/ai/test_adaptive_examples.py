import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.ai.context.adaptive.examples import select_examples, validate_examples
from backend.app.ai.context.adaptive import learning, settings, store
from backend.app.ai.context.intent import classify_agent_intent
from backend.app.ai.context import selection
from backend.app.ai.context.contracts import AgentIntentClassification, AgentRoutingDecision
from backend.tests.ai.test_adaptive_patterns import evidence_rows, NOW
from backend.tests.ai import test_adaptive_store as fixtures

CLASSIFICATION = AgentRoutingDecision(intent="activity_query", time_scope="today", include_activities=True, include_exams=False)


def reviewed_examples(count=5):
    rows = evidence_rows(count)
    for index, row in enumerate(rows):
        row["event"].request_excerpt = f"Help me choose a focus for course {index}"
        row["label"].classification = CLASSIFICATION
        row["label"].example_approved = True
    return rows


class AdaptiveExampleTests(unittest.TestCase):
    def test_relevance_approval_versions_and_budget(self):
        rows = reviewed_examples()
        examples = select_examples(rows, "Choose a course focus", now=NOW)
        self.assertEqual(len(examples), 3)
        self.assertLessEqual(len(json.dumps(examples)), 1800)
        self.assertEqual(select_examples(rows, "Tell a penguin joke", now=NOW), [])
        for row in rows:
            row["label"].example_approved = False
        self.assertEqual(select_examples(rows, "Choose a course focus", now=NOW), [])
        rows = reviewed_examples()
        for row in rows:
            row["event"].router_version = "old"
        self.assertEqual(select_examples(rows, "Choose a course focus", now=NOW), [])
        with self.assertRaises(ValueError):
            validate_examples([{**examples[0], "owner_id": "private"}])

    def test_classifier_receives_only_bounded_reviewed_request_and_classification(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=AgentIntentClassification(
            **CLASSIFICATION.model_dump(), confidence="high"))
        examples = select_examples(reviewed_examples(), "Choose a course focus", now=NOW)
        classify_agent_intent(client, "Choose a course focus", [], "test-model", confirmed_examples=examples)
        sent = json.loads(client.responses.parse.call_args.kwargs["input"][0]["content"])
        self.assertEqual(set(sent), {"recent_conversation", "current_message", "confirmed_examples"})
        self.assertEqual(set(sent["confirmed_examples"][0]), {"request", "classification"})
        self.assertFalse(client.responses.parse.call_args.kwargs["store"])

    def test_shadow_never_adds_examples_to_semantic_call(self):
        for mode, included in (("shadow", False), ("active", True)):
            with self.subTest(mode=mode), \
                    patch.object(selection, "assess_stage_one", return_value={"selection": fixtures.EMPTY, "confident": False}), \
                    patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(
                        **CLASSIFICATION.model_dump(), confidence="high")) as classifier:
                selection.select_agent_context(Mock(), "Choose a course focus", [], "test-model",
                    adaptive_snapshot={"mode": mode, "patterns": [], "examples_enabled": True,
                                       "examples": select_examples(reviewed_examples(), "Choose a course focus", now=NOW)})
            self.assertEqual("confirmed_examples" in classifier.call_args.kwargs, included)


class AdaptiveExampleScopeTests(unittest.TestCase):
    setUp = fixtures.AdaptiveStoreTests.setUp

    def test_examples_respect_owner_and_revoked_sharing(self):
        row = reviewed_examples(1)[0]
        event = row["event"].model_dump()
        event.update(owner_id="owner-a", conversation_id=self.a)
        store.record_event(self.connection, event)
        learning.apply_reviewed_label(self.connection, "owner-a", event["event_id"], row["label"].model_dump())
        self.assertEqual(store.load_eligible_evidence(self.connection, "owner-a", self.other), [])
        fixtures.storage.set_memory_sharing(self.connection, self.a, "owner-a", True)
        rows = store.load_eligible_evidence(self.connection, "owner-a", self.other)
        self.assertEqual(len(select_examples(rows, "Choose a course focus", now=NOW)), 1)
        fixtures.storage.set_memory_sharing(self.connection, self.a, "owner-a", False)
        self.assertEqual(select_examples(store.load_eligible_evidence(self.connection, "owner-a", self.other),
                                         "Choose a course focus", now=NOW), [])
