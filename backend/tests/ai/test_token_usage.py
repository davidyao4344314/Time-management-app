"""Numeric usage/estimate telemetry only: fake API replies, no real requests."""

import asyncio
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.infrastructure.token_usage import estimate_tokens, parse_with_usage, token_usage_session
from backend.app.ai.agent import service
from backend.app.ai.context import selection
from backend.app.ai.agent.contracts import AgentProposal


def response(parsed=None, input_tokens=100, output_tokens=20, **extra):
    return SimpleNamespace(status="completed", output_parsed=parsed or {"message": "Received.", "actions": []},
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=5),
            output_tokens_details=SimpleNamespace(reasoning_tokens=10)), **extra)


def parameters(**changes):
    payload = {"request": "Help me study.", "observations": {"activities": {"today": []},
        "exams": {"upcoming": []}, "files": {"text": "private-excerpt"}, "memory": {"text": "private-memory"}}}
    return {"model": "offline-model", "instructions": "Be concise.", "text_format": AgentProposal,
            "input": [{"role": "user", "content": json.dumps(payload)}], **changes}


class TokenUsageTests(unittest.TestCase):
    def test_reported_counts_include_recovery_and_do_not_double_count_subsets(self):
        client = Mock()
        with token_usage_session() as usage:
            for index, stage in enumerate(["stage_2", "stage_3", "main_agent", "main_agent"], 1):
                client.responses.parse.return_value = response(input_tokens=index * 100, output_tokens=index * 10)
                parse_with_usage(client, stage, **parameters())
            result = usage.snapshot()
        self.assertEqual(result["totals"]["input_tokens"], 1000)
        self.assertEqual(result["totals"]["output_tokens"], 100)
        self.assertEqual(result["totals"]["total_tokens"], 1100)
        self.assertEqual(result["totals"]["cached_input_tokens"], 20)
        self.assertEqual(result["totals"]["reasoning_output_tokens"], 40)
        self.assertEqual(result["totals"]["measurement"], "reported")
        self.assertEqual(result["totals"]["model_calls"], 4)
        self.assertEqual(result["stages"][0]["total_tokens"], 0)
        self.assertIn("Recovery", result["stages"][-1]["label"])
        self.assertEqual(client.responses.parse.call_count, 4)
        self.assertNotIn("private-excerpt", json.dumps(result))
        self.assertNotIn("private-memory", json.dumps(result))

    def test_estimates_have_components_but_no_claim_about_hidden_output(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={"message": "Private answer", "actions": []})
        with token_usage_session() as usage:
            parse_with_usage(client, "main_agent", **parameters())
        item = usage.snapshot()["stages"][-1]
        self.assertEqual(item["measurement"], "estimated")
        self.assertGreater(item["input_tokens"], 0)
        self.assertGreater(item["output_tokens"], 0)
        self.assertIsNone(item["reasoning_output_tokens"])
        self.assertIsNone(item["cached_input_tokens"])
        self.assertEqual(item["input_tokens"], sum(item["context_estimates"].values()))
        self.assertGreater(item["context_estimates"]["response_schema"], 0)
        self.assertGreater(item["context_estimates"]["files"], 0)
        self.assertNotIn("Private answer", json.dumps(item))

    def test_failed_calls_have_unknown_output_not_zero(self):
        client = Mock()
        client.responses.parse.side_effect = RuntimeError("private-error-secret")
        with token_usage_session() as usage:
            with self.assertRaises(RuntimeError):
                parse_with_usage(client, "stage_2", **parameters())
        result = usage.snapshot()
        item = next(item for item in result["stages"] if item["stage"] == "stage_2")
        self.assertIsNone(item["output_tokens"])
        self.assertIsNone(result["totals"]["total_tokens"])
        self.assertNotIn("private-error-secret", json.dumps(result))
        self.assertEqual(result["totals"]["model_calls"], 1)

    def test_dictionary_usage_zeroes_are_valid_but_boolean_and_negative_counts_are_not(self):
        client = Mock()
        client.responses.parse.return_value = response()
        client.responses.parse.return_value.usage = {"input_tokens": 0, "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}
        with token_usage_session() as usage:
            parse_with_usage(client, "main_agent", **parameters())
        self.assertEqual(usage.snapshot()["totals"]["measurement"], "reported")
        self.assertEqual(usage.snapshot()["totals"]["total_tokens"], 0)
        for invalid in (True, -1):
            client.responses.parse.return_value.usage["input_tokens"] = invalid
            with token_usage_session() as usage:
                parse_with_usage(client, "main_agent", **parameters())
            self.assertEqual(usage.snapshot()["totals"]["measurement"], "estimated")

    def test_mixed_counts_are_labelled_and_skipped_classifiers_cost_zero(self):
        client = Mock()
        with token_usage_session() as usage:
            client.responses.parse.return_value = response()
            parse_with_usage(client, "main_agent", **parameters())
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={"message": "Reply"})
            parse_with_usage(client, "main_agent", **parameters())
        result = usage.snapshot()
        self.assertEqual(result["totals"]["measurement"], "mixed")
        self.assertIsNone(result["totals"]["reasoning_output_tokens"])
        self.assertTrue(all(item["total_tokens"] == 0 and item["status"] == "not_used"
                            for item in result["stages"] if item["stage"] in {"stage_2", "stage_3"}))

    def test_instrumentation_failure_cannot_break_the_model_request_or_claim_zero(self):
        client = Mock()
        client.responses.parse.return_value = response()
        params = parameters(text_format=object())
        with token_usage_session() as usage:
            self.assertIs(parse_with_usage(client, "main_agent", **params), client.responses.parse.return_value)
        self.assertEqual(usage.snapshot()["totals"]["measurement"], "unavailable")
        self.assertIsNone(usage.snapshot()["totals"]["input_tokens"])

    def test_request_arguments_response_and_call_count_remain_unchanged(self):
        client = Mock()
        expected = response()
        client.responses.parse.return_value = expected
        params = parameters(store=False, max_output_tokens=3000)
        with token_usage_session(enabled=False):
            self.assertIs(parse_with_usage(client, "main_agent", **params), expected)
        client.responses.parse.assert_called_once_with(**params)

    def test_nested_and_concurrent_requests_do_not_share_counters(self):
        client = Mock()
        client.responses.parse.return_value = response()
        with token_usage_session() as outer:
            parse_with_usage(client, "main_agent", **parameters())
            with token_usage_session() as inner:
                parse_with_usage(client, "stage_2", **parameters())
            parse_with_usage(client, "main_agent", **parameters())
        self.assertEqual(outer.snapshot()["totals"]["model_calls"], 2)
        self.assertEqual(inner.snapshot()["totals"]["model_calls"], 1)

        async def run(stage):
            with token_usage_session() as usage:
                await asyncio.sleep(0)
                parse_with_usage(client, stage, **parameters())
                return usage.snapshot()

        async def concurrent():
            return await asyncio.gather(run("stage_2"), run("main_agent"))

        for result in asyncio.run(concurrent()):
            self.assertEqual(result["totals"]["model_calls"], 1)

    def test_utf8_estimator_is_explicitly_approximate(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)
        self.assertEqual(estimate_tokens(None), 0)
        self.assertEqual(estimate_tokens("学习"), 2)


class AgentTokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for patcher in (
            patch.object(service, "is_openai_api_key_configured", return_value=True),
            patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-private-key"}),
            patch.object(service, "get_agent_model_settings", return_value={"model": "main-model", "reasoning_effort": "none"}),
            patch.object(service, "get_max_recent_turns", return_value=5),
            patch.object(service, "build_activity_observation", return_value={"count": 0, "today": []}),
            patch.object(service, "build_exam_observation", return_value={"count": 0, "upcoming": []}),
        ):
            self.stack.enter_context(patcher)
        factory = self.stack.enter_context(patch.object(service, "OpenAI"))
        self.client = factory.return_value.__enter__.return_value
        self.connection = Mock()

    def test_stage_one_request_reports_only_main_model_usage(self):
        self.client.responses.parse.return_value = response(input_tokens=900, output_tokens=100)
        result = service.get_agent_proposal(self.connection, "What am I doing today?", [], include_context=True)
        usage = result["agent_context"]["token_usage"]
        self.assertEqual(usage["totals"]["total_tokens"], 1000)
        self.assertEqual(usage["totals"]["model_calls"], 1)
        self.assertEqual(result["agent_context"]["routing"]["stage"], "stage_1")
        self.client.responses.parse.assert_called_once()
        self.connection.execute.assert_not_called()
        self.assertNotIn("offline-private-key", json.dumps(usage))

    def test_classifier_fallback_main_and_recovery_are_all_accounted_once(self):
        decision = {"intent": "study_planning", "time_scope": "today", "include_activities": False,
                    "include_exams": True, "exam_scope": "upcoming"}
        self.client.responses.parse.side_effect = [
            response({**decision, "confidence": "low"}, 100, 10), response(decision, 200, 20),
            response({"message": None, "actions": [], "missing_context": [{"source": "activities", "time_scope": "today"}]}, 300, 30),
            response(input_tokens=400, output_tokens=40),
        ]
        with patch.object(selection, "assess_stage_one", return_value={"confident": False, "selection": None}):
            result = service.get_agent_proposal(self.connection, "Help me focus.", [], include_context=True)
        usage = result["agent_context"]["token_usage"]
        self.assertEqual(usage["totals"]["total_tokens"], 1100)
        self.assertEqual(usage["totals"]["model_calls"], 4)
        self.assertEqual([item["stage"] for item in usage["stages"]], ["stage_1", "stage_2", "stage_3", "main_agent", "main_agent"])
        self.assertEqual(result["agent_context"]["context_recovery"]["main_agent_attempts"], 2)
        self.assertEqual(self.client.responses.parse.call_count, 4)

    def test_failed_classifier_usage_is_not_falsely_reported_as_zero(self):
        decision = {"intent": "general_question", "time_scope": "unspecified", "include_activities": False, "include_exams": False}
        self.client.responses.parse.side_effect = [RuntimeError("private-provider-error"), response(decision), response()]
        with patch.object(selection, "assess_stage_one", return_value={"confident": False, "selection": None}):
            result = service.get_agent_proposal(self.connection, "Help me focus.", [], include_context=True)
        usage = result["agent_context"]["token_usage"]
        self.assertEqual(usage["totals"]["measurement"], "mixed")
        self.assertIsNone(usage["totals"]["total_tokens"])
        self.assertEqual(usage["totals"]["model_calls"], 3)
        self.assertNotIn("private-provider-error", json.dumps(usage))


if __name__ == "__main__":
    unittest.main()
