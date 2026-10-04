"""The direct classifier evaluator is offline by default and isolates paid calls."""

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.dev import stage_two_check as check


class StageTwoCheckTests(unittest.TestCase):
    def test_default_preview_does_not_read_configuration_or_call_openai(self):
        with patch.object(check, "is_openai_api_key_configured") as configured, \
                patch.object(check, "OpenAI") as client, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check.main([]), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual([case["case"] for case in preview["cases"]], list("ABCDEFGHIJKLMNOP"))
        self.assertIn("no model calls", preview["mode"])
        configured.assert_not_called()
        client.assert_not_called()

    def test_explicit_live_case_calls_only_the_classifier_once(self):
        with patch.object(check, "is_openai_api_key_configured", return_value=True), \
                patch.dict(check.os.environ, {"OPENAI_API_KEY": "offline-test-key"}), \
                patch.object(check, "OpenAI") as client_class, redirect_stdout(io.StringIO()) as output:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
                "intent": "general_question", "time_scope": "tomorrow",
                "include_activities": True, "include_exams": False,
                "memory": None, "confidence": "high",
            })
            self.assertEqual(check.main(["--case", "A", "--llm"]), 0)
        client.responses.parse.assert_called_once()
        request = json.loads(client.responses.parse.call_args.kwargs["input"][0]["content"])
        self.assertEqual(request, {
            "recent_conversation": [], "current_message": check.CASES["A"]["message"],
        })
        self.assertIn("Passed 1/1 cases.", output.getvalue())
        self.assertNotIn("offline-test-key", output.getvalue())

    def test_valid_but_wrong_dependency_selection_fails_the_case(self):
        with patch.object(check, "is_openai_api_key_configured", return_value=True), \
                patch.dict(check.os.environ, {"OPENAI_API_KEY": "offline-test-key"}), \
                patch.object(check, "OpenAI") as client_class, redirect_stdout(io.StringIO()) as output:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
                "intent": "general_question", "time_scope": "tomorrow",
                "include_activities": False, "include_exams": False,
                "memory": None, "confidence": "high",
            })
            self.assertEqual(check.main(["--case", "A", "--llm"]), 1)
        self.assertIn('"passed": false', output.getvalue())

    def test_request_failure_does_not_print_exception_details(self):
        with patch.object(check, "is_openai_api_key_configured", return_value=True), \
                patch.dict(check.os.environ, {"OPENAI_API_KEY": "offline-test-key"}), \
                patch.object(check, "OpenAI") as client_class, redirect_stdout(io.StringIO()) as output:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.side_effect = RuntimeError("offline-test-key private details")
            self.assertEqual(check.main(["--case", "A", "--llm"]), 1)
        self.assertIn("Classifier request failed", output.getvalue())
        self.assertNotIn("offline-test-key", output.getvalue())
        self.assertNotIn("private details", output.getvalue())

    def test_all_fixture_selections_are_consistent_with_the_adapter(self):
        # This tests evaluator wiring only. Mocked classifications do not prove
        # that the live model understands these messages.
        for label, case in check.CASES.items():
            with self.subTest(case=label):
                expected = case["expected"]
                client = Mock()
                memory = None
                if expected["memory_scope"]:
                    memory = {"sources": ["compressed_archive"], "scope": "global", "query": {
                        "time_reference": expected["memory_time_reference"], "search_terms": ["study plan"],
                    }}
                client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
                    "intent": "general_question", "confidence": "high", "memory": memory,
                    "time_scope": expected["activities_scope"] or expected["exam_scope"] or "unspecified",
                    "include_activities": expected["activities_scope"] is not None,
                    "include_exams": expected["include_exams"], "exam_scope": expected["exam_scope"],
                })
                self.assertTrue(check.check_case(client, label)["passed"])
                client.responses.parse.assert_called_once()

    def test_semantic_evaluator_does_not_hide_exclusion_errors_with_backend_policy(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
            "intent": "general_question", "time_scope": "tomorrow", "confidence": "high",
            "include_activities": True, "include_exams": False, "exam_scope": None,
        })
        self.assertFalse(check.check_case(client, "L")["passed"])

    def test_semantic_evaluator_rejects_an_incorrect_exam_horizon(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
            "intent": "study_planning", "time_scope": "tomorrow", "confidence": "high",
            "include_activities": True, "include_exams": True, "exam_scope": "tomorrow",
        })
        self.assertFalse(check.check_case(client, "K")["passed"])


if __name__ == "__main__":
    unittest.main()
