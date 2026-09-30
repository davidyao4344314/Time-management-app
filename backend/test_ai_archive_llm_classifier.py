"""Offline Stage 3 tests; all OpenAI responses are mocked."""

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import ai_archive_llm_classifier as classifier
from backend.app.ai_archive_protection import classify_compaction_candidates


MANUAL_CASES = (
    "Maybe I want to finish this study planner before exams.",
    "Maybe we should always make the AI ask before changing activities.",
    "Why is this Python loop printing twice?",
    "I don't know if I want dark mode.",
    "We might use semantic search later, but not yet.",
    "Thanks, it works now.",
)


def uncertain(user, assistant="Assistant response"):
    return {
        "status": "uncertain",
        "category": None,
        "matched_rule": None,
        "archived_turn": {
            "session_id": "test-session",
            "timestamp": "2026-09-30T10:00:00+00:00",
            "turn": {"user": user, "assistant": {"message": assistant, "actions": []}},
        },
    }


def decision(index, status="protected", category="goal", reason="May matter later."):
    return {
        "candidate_index": index,
        "status": status,
        "category": category,
        "reason": reason,
    }


def response(*decisions, status="completed"):
    return SimpleNamespace(
        status=status,
        output_parsed={"classifications": list(decisions)},
    )


class ArchiveLLMClassifierTests(unittest.TestCase):
    def setUp(self):
        self.key_patch = patch.object(classifier, "is_openai_api_key_configured", return_value=True)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.env_patch = patch.dict(classifier.os.environ, {"OPENAI_API_KEY": "test-key"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client_patch = patch.object(classifier, "OpenAI")
        self.openai = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = self.openai.return_value.__enter__.return_value

    def test_only_uncertain_text_is_sent_and_stage_two_point_five_is_unchanged(self):
        stage_two_point_five = classify_compaction_candidates([
            uncertain("Remember this: preserve my goal.")["archived_turn"],
            uncertain("Can you explain what a queue is?")["archived_turn"],
            uncertain("Maybe I want to finish the planner.")["archived_turn"],
            uncertain("I am not sure about dark mode.")["archived_turn"],
        ])
        original = deepcopy(stage_two_point_five)
        self.client.responses.parse.return_value = response(
            decision(1, "compactable", "casual_conversation", "No durable preference established."),
            decision(0, "protected", "goal", "A lasting project goal."),
        )

        result = classifier.classify_uncertain_archive_candidates(
            stage_two_point_five["uncertain"],
        )

        self.assertEqual(stage_two_point_five, original)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["protected_count"], 1)
        self.assertEqual(result["compactable_count"], 1)
        self.assertEqual(result["protected"][0]["archived_turn"]["turn"]["user"],
                         "Maybe I want to finish the planner.")
        self.assertEqual(result["compactable"][0]["archived_turn"]["turn"]["user"],
                         "I am not sure about dark mode.")

        call = self.client.responses.parse.call_args.kwargs
        payload = json.loads(call["input"][0]["content"])
        self.assertEqual(list(payload), ["uncertain_candidates"])
        self.assertEqual(
            [item["candidate_index"] for item in payload["uncertain_candidates"]],
            [0, 1],
        )
        self.assertEqual(
            set(payload["uncertain_candidates"][0]),
            {"candidate_index", "timestamp", "user", "assistant"},
        )
        self.assertNotIn("Remember this: preserve my goal.", str(payload))
        self.assertNotIn("Can you explain what a queue is?", str(payload))
        self.assertNotIn("test-key", str(payload))
        self.assertEqual(call["text_format"], classifier.ArchiveClassificationBatch)
        self.assertEqual(call["model"], classifier.ARCHIVE_CLASSIFIER_MODEL)
        self.assertEqual(call["reasoning"], {"effort": "none"})
        self.assertFalse(call["store"])
        self.assertNotIn("study planning assistant", call["instructions"].lower())

    def test_empty_input_does_not_check_key_or_call_model(self):
        result = classifier.classify_uncertain_archive_candidates([])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["protected"], [])
        classifier.is_openai_api_key_configured.assert_not_called()
        self.openai.assert_not_called()

    def test_missing_key_or_config_error_protects_every_uncertain_turn(self):
        entries = [uncertain("Maybe a durable preference"), uncertain("One-off question")]
        for key_effect in (False, OSError("configuration unavailable")):
            with self.subTest(key_effect=key_effect):
                classifier.is_openai_api_key_configured.side_effect = (
                    key_effect if isinstance(key_effect, Exception) else None
                )
                classifier.is_openai_api_key_configured.return_value = (
                    False if isinstance(key_effect, Exception) else key_effect
                )
                result = classifier.classify_uncertain_archive_candidates(entries)
                self.assertEqual(result["protected_count"], 2)
                self.assertEqual(result["compactable_count"], 0)
                self.assertEqual(entries[0]["status"], "uncertain")
        self.openai.assert_not_called()

    def test_invalid_or_incomplete_model_result_protects_the_whole_batch(self):
        entries = [uncertain("First"), uncertain("Second")]
        bad_responses = (
            response(decision(0)),  # Missing candidate 1.
            response(decision(0), decision(0)),  # Duplicate reference.
            response(decision(0), decision(9)),  # Unknown reference.
            response(decision(0), decision(1, "uncertain", "goal")),
            response(decision(0), decision(1, "compactable", "goal")),
            response(decision(0), decision(1, reason="  ")),
            response(decision(0), decision(1), status="incomplete"),
            SimpleNamespace(status="completed", output_parsed=None),
        )
        for bad in bad_responses:
            with self.subTest(bad=bad):
                self.client.responses.parse.return_value = bad
                result = classifier.classify_uncertain_archive_candidates(entries)
                self.assertEqual(result["protected_count"], 2)
                self.assertEqual(result["compactable_count"], 0)

        self.client.responses.parse.side_effect = TimeoutError("timeout")
        result = classifier.classify_uncertain_archive_candidates(entries)
        self.assertEqual(result["protected_count"], 2)

    def test_batching_preserves_order_and_failure_affects_only_its_batch(self):
        entries = [uncertain(f"Possibly important turn {index}") for index in range(12)]
        self.client.responses.parse.side_effect = [
            response(*[
                decision(index, "compactable", "transient_information", "Short-lived.")
                for index in range(10)
            ]),
            ValueError("invalid JSON"),
        ]
        result = classifier.classify_uncertain_archive_candidates(entries)

        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.assertEqual(result["compactable_count"], 10)
        self.assertEqual(result["protected_count"], 2)
        self.assertEqual(
            [item["candidate_index"] for item in result["compactable"]], list(range(10)),
        )
        self.assertEqual(
            [item["candidate_index"] for item in result["protected"]], [10, 11],
        )
        second_payload = json.loads(self.client.responses.parse.call_args.kwargs["input"][0]["content"])
        self.assertEqual(
            [item["candidate_index"] for item in second_payload["uncertain_candidates"]],
            [10, 11],
        )

    def test_six_manual_case_shapes_and_references(self):
        # Mocked output checks the contract; live semantic quality needs an
        # explicit, billable API test by the user.
        entries = [uncertain(text) for text in MANUAL_CASES]
        self.client.responses.parse.return_value = response(
            decision(0, "protected", "goal", "An ongoing project goal."),
            decision(1, "protected", "constraint", "Requires approval for future changes."),
            decision(2, "compactable", "temporary_debugging", "One-off loop issue."),
            decision(3, "compactable", "casual_conversation", "No lasting preference."),
            decision(4, "protected", "project_architecture", "A current design decision."),
            decision(5, "compactable", "resolved_issue", "The issue is finished."),
        )
        result = classifier.classify_uncertain_archive_candidates(entries)
        self.assertEqual([item["candidate_index"] for item in result["protected"]], [0, 1, 4])
        self.assertEqual([item["candidate_index"] for item in result["compactable"]], [2, 3, 5])
        self.assertEqual(result["candidate_count"], 6)

    def test_rejects_non_uncertain_input_and_bad_batch_size_before_api_call(self):
        with self.assertRaisesRegex(ValueError, "Only Stage 2.5 uncertain"):
            classifier.classify_uncertain_archive_candidates([{
                **uncertain("Protected"), "status": "protected",
            }])
        for batch_size in (0, -1, True, "10"):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                classifier.classify_uncertain_archive_candidates([], batch_size=batch_size)
        self.openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
