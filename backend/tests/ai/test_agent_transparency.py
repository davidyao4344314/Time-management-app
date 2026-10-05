"""Inspector metadata tests: no network, production database or archive writes."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.ai.agent import service, reasoning
from backend.app.ai.agent.transparency import build_agent_context
from backend.app.ai.context import selection
from backend.app.ai.context.contracts import AgentIntentClassification
from backend.app.api import ai


SCHEDULE = {"activities_scope": "today", "include_exams": False, "exam_scope": None}
DECISION = {"intent": "study_planning", "time_scope": "today",
            "include_activities": True, "include_exams": True}
EMPTY = {"status": "empty", "items": [], "truncated": False, "unavailable_sources": []}


class RoutingTransparencyTests(unittest.TestCase):
    def test_stage_one_reports_actual_route_without_inventing_intent(self):
        trace = {}
        plain = selection.select_agent_context(Mock(), "What am I doing today?", [], "model")
        traced = selection.select_agent_context(Mock(), "What am I doing today?", [], "model", trace=trace)
        self.assertEqual(plain, traced)
        self.assertEqual(trace["stage"], "stage_1")
        self.assertEqual(trace["time_scope"], "today")
        self.assertIsNone(trace["intent"])

    def test_stage_two_three_and_safe_fallback_report_actual_stage(self):
        for stage in ("stage_2", "stage_3", "safe_fallback"):
            with self.subTest(stage=stage):
                trace = {}
                with patch.object(selection, "assess_stage_one", return_value={"confident": False}), \
                        patch.object(selection, "classify_agent_intent") as two, \
                        patch.object(selection, "classify_stage_three") as three:
                    two.return_value = AgentIntentClassification(**DECISION, confidence="high")
                    three.return_value = DECISION
                    if stage != "stage_2":
                        two.side_effect = RuntimeError("PRIVATE MODEL INTERNALS")
                    if stage == "safe_fallback":
                        three.side_effect = RuntimeError("PRIVATE MODEL INTERNALS")
                    plain = selection.select_agent_context(Mock(), "Help me focus", [], "model")
                    traced = selection.select_agent_context(Mock(), "Help me focus", [], "model", trace=trace)
                self.assertEqual(plain, traced)
                self.assertEqual(trace["stage"], stage)
                self.assertNotIn("PRIVATE", json.dumps(trace))
                self.assertEqual(trace["status"], "fallback" if stage == "safe_fallback" else "matched")


class ContextMetadataTests(unittest.TestCase):
    def test_sources_authority_bounded_excerpts_and_provenance(self):
        items = [{"source": source, "id": source + "-id", "text": "sk-abcdefghijklmnopqrst " + "x" * 500,
                  "timestamp": "2026-09-23T10:00:00+12:00", "source_refs": ["turn-1"],
                  "type": "constraint" if source == "durable" else None}
                 for source in ("raw_archive", "compressed_archive", "durable")]
        lookup = {"phase": "initial", "sources": [item["source"] for item in items],
                  "result": {**EMPTY, "status": "ok", "items": items}, "used_in_model": True}
        result = build_agent_context({}, SCHEDULE, 2, [lookup])
        sources = {item["source"]: item for item in result["context_sources"]}
        self.assertTrue(sources["activities"]["selected"])
        self.assertFalse(sources["exams"]["selected"])
        self.assertEqual(sources["activities"]["authority"], "current")
        self.assertEqual(sources["compressed_archive"]["authority"], "historical_summary")
        self.assertEqual(sources["durable"]["authority"], "historical")
        self.assertTrue(sources["recent_memory"]["selected"])
        for item in result["retrieved_memory"]:
            self.assertLessEqual(len(item["excerpt"]), 241)
            self.assertEqual(item["source_refs"], ["turn-1"])
            self.assertTrue(item["used_in_model"])
        self.assertNotIn("sk-abcdefghijklmnopqrst", json.dumps(result))
        self.assertIn("[redacted API key]", json.dumps(result))

    def test_no_match_unavailable_and_not_requested_are_distinct(self):
        for status, expected in (("empty", "No matching"), ("unavailable", "could not")):
            result = build_agent_context({}, SCHEDULE, 0, [{"phase": "initial",
                "sources": ["raw_archive"], "result": {**EMPTY, "status": status}, "used_in_model": True}])
            self.assertEqual(result["retrieved_memory"], [])
            self.assertIn(expected, result["memory_message"])
        self.assertIn("not requested", build_agent_context({}, SCHEDULE, 0, [])["memory_message"])


class ServiceTransparencyTests(unittest.TestCase):
    def setUp(self):
        for p in (
            patch.object(service, "is_openai_api_key_configured", return_value=True),
            patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-test-key"}),
            patch.object(service, "get_agent_model_settings", return_value={"model": "existing-model", "reasoning_effort": "none"}),
            patch.object(service, "get_max_recent_turns", return_value=5),
            patch.object(service, "OpenAI"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_metadata_does_not_change_message_actions_or_model_input(self):
        proposal = {"message": "Your schedule is clear.", "actions": [], "memory_request": None}
        observation = {"activities": {"today": []}}
        with patch.object(service, "collect_agent_observations", return_value=observation), \
                patch.object(reasoning, "request_agent_response", return_value=SimpleNamespace(status="completed", output_parsed=proposal)) as model:
            plain = service.get_agent_proposal(Mock(), "What am I doing today?", [])
            before = model.call_args.args[1:]
            traced = service.get_agent_proposal(Mock(), "What am I doing today?", [], include_context=True)
            after = model.call_args.args[1:]
        self.assertEqual(before, after)
        self.assertEqual(plain, {key: value for key, value in traced.items() if key != "agent_context"})
        self.assertEqual(traced["agent_context"]["routing"]["stage"], "stage_1")
        self.assertEqual(traced["agent_context"]["model"], "existing-model")
        self.assertEqual(model.call_count, 2)  # One per request, no extra inspector call.

    def test_failed_followup_is_visible_but_not_claimed_as_model_input(self):
        proposal = {"message": "Looking back.", "actions": [],
                    "memory_request": {"time_reference": "last_week", "search_terms": ["COMPSCI"]}}
        with patch.object(service, "select_agent_context", return_value=SCHEDULE), \
                patch.object(service, "collect_agent_observations", return_value={"activities": {}}), \
                patch.object(service, "build_memory_observation", return_value=EMPTY), \
                patch.object(reasoning, "request_agent_response", return_value=SimpleNamespace(status="completed", output_parsed=proposal)) as model:
            result = service.get_agent_proposal(Mock(), "Old discussion", [], session_id="one", include_context=True)
        lookup = result["agent_context"]["memory_lookups"][0]
        self.assertEqual(lookup["phase"], "followup")
        self.assertFalse(lookup["used_in_model"])
        self.assertEqual(result["agent_context"]["retrieved_memory"], [])
        self.assertEqual(model.call_count, 1)

    def test_endpoint_metadata_is_not_saved_to_conversation(self):
        app = FastAPI()
        app.include_router(ai.router)
        proposal = {"message": "A proposal, not executed.", "actions": [{"tool": "add_activity", "arguments": {"name": "Study"}}],
                    "memory_request": None, "agent_context": {"routing": {"stage": "stage_1"}}}
        connection = Mock()
        with patch.object(ai, "is_openai_api_key_configured", return_value=True), \
                patch.object(ai, "sign_session", return_value="test-signature"), \
                patch.object(ai, "enforce_recent_limit"), \
                patch.object(ai, "get_recent_turns", return_value=[]), \
                patch.object(ai.sqlite3, "connect", return_value=connection) as connect, \
                patch.object(ai, "get_agent_proposal", return_value=proposal) as propose, \
                patch.object(ai, "add_completed_turn") as save:
            response = TestClient(app).post("/ai/propose", json={"message": "Plan study"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), proposal)
        self.assertTrue(propose.call_args.kwargs["include_context"])
        self.assertNotIn("agent_context", save.call_args.args[2])
        self.assertIn("mode=ro", connect.call_args.args[0])
        connection.execute.assert_not_called()
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
