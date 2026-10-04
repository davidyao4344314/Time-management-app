"""Routing-to-observation regressions with real, read-only in-memory SQLite.

Model replies are fakes. These tests verify transmission and backend behavior,
not live semantic classification or the quality of the main agent's answer.
"""

import json
import sqlite3
import unittest
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.app.database import create_tables
from backend.app.planner.activities import add_activity
from backend.app.planner.exams import add_exam
from backend.app.ai.context import selection as routing
from backend.app.ai.context.intent import context_from_classification
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.agent import reasoning, service


NOW = datetime(2026, 10, 4, 9, 30, tzinfo=ZoneInfo("Pacific/Auckland"))


class ContextSelectionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        create_tables(self.connection)
        activity_columns = ["name", "category", "subject", "activity_type", "date", "weekday", "start_time", "end_time"]
        for values in (
            ["Today current", "Study", "PHYSICS", "one_time", "2026-10-04", None, "09:00", "10:00"],
            ["Today next", "Study", "MATHS", "one_time", "2026-10-04", None, "14:00", "15:00"],
            ["Monday lecture", "University", "COMPSCI", "weekly", None, "Monday", "10:00", "11:00"],
            ["Tomorrow date-only", "Canvas", "COMPSCI", "one_time", "2026-10-05", None, None, None],
        ):
            add_activity(self.connection, activity_columns, values)
        exam_columns = ["name", "category", "subject", "date", "start_time", "end_time"]
        for values in (
            ["Today exam", "Canvas", "PHYSICS", "2026-10-04", "12:00", "13:00"],
            ["Tomorrow exam", "Canvas", "MATHS", "2026-10-05", None, None],
            ["Friday exam", "Canvas", "COMPSCI", "2026-10-09", "14:00", "16:00"],
            ["Updated exam", "Canvas", "COMPSCI", "2026-10-12", None, None],
        ):
            add_exam(self.connection, exam_columns, values)
        self.connection.execute("PRAGMA query_only=ON")
        self.original_changes = self.connection.total_changes
        self.stack.enter_context(patch("backend.app.planner.calendar.local_now", return_value=NOW))
        self.stack.enter_context(patch("backend.app.infrastructure.clock.local_now", return_value=NOW))
        self.stack.enter_context(patch.object(reasoning, "get_max_recent_turns", return_value=5))

    def tearDown(self):
        self.assertEqual(self.connection.total_changes, self.original_changes)

    def test_stage_two_windows_reach_actual_recurrence_and_exam_builders(self):
        for intent in ("study_planning", "general_question", "schedule_query"):
            with self.subTest(intent=intent), patch.object(routing, "assess_stage_one", return_value={
                "selection": None, "confident": False, "reason": "fixture",
            }):
                client = Mock()
                client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
                    "intent": intent, "time_scope": "tomorrow", "exam_scope": "upcoming",
                    "include_activities": True, "include_exams": True, "confidence": "high",
                })
                selected = routing.select_agent_context(client, "Help me study tomorrow.", [], "test-model")
                context = collect_agent_observations(self.connection, selected)
                self.assertEqual(context["activities"]["period"], {"start": "2026-10-05", "end": "2026-10-05"})
                self.assertEqual([item["name"] for item in context["activities"]["upcoming_7d"]],
                                 ["Monday lecture", "Tomorrow date-only"])
                self.assertNotIn("current", context["activities"])
                self.assertEqual(context["activities"]["busy"], {"2026-10-05": [["10:00", "11:00"]]})
                self.assertEqual(context["exams"]["count"], 4)
                self.assertIn("Updated exam", [item["name"] for item in context["exams"]["upcoming"]])
                classifier_input = json.loads(client.responses.parse.call_args.kwargs["input"][0]["content"])
                self.assertNotIn("observations", classifier_input)

    def test_explicit_exam_scopes_filter_real_rows_without_losing_date_only_exams(self):
        for scope, expected in (
            ("today", ["Today exam"]), ("tomorrow", ["Tomorrow exam"]),
            ("this_week", ["Today exam"]), ("next_week", ["Tomorrow exam", "Friday exam"]),
            ("month", ["Today exam", "Tomorrow exam", "Friday exam", "Updated exam"]),
        ):
            with self.subTest(scope=scope):
                selected = context_from_classification({
                    "intent": "general_question", "time_scope": scope, "exam_scope": scope,
                    "include_activities": False, "include_exams": True,
                })
                context = collect_agent_observations(self.connection, selected)
                self.assertNotIn("activities", context)
                self.assertEqual([item["name"] for item in context["exams"]["upcoming"]], expected)
                for item in context["exams"]["upcoming"]:
                    if item["name"] in ("Tomorrow exam", "Updated exam"):
                        self.assertIsNone(item["start"])
                        self.assertIsNone(item["end"])

    def test_same_requirements_do_not_change_when_intent_label_changes(self):
        for intent in ("study_planning", "schedule_query", "exam_query", "activity_query", "general_question"):
            for activities in (False, True):
                for exams in (False, True):
                    with self.subTest(intent=intent, activities=activities, exams=exams):
                        selected = context_from_classification({
                            "intent": intent, "time_scope": "tomorrow", "include_activities": activities,
                            "include_exams": exams, "exam_scope": "this_week" if exams else None,
                        })
                        self.assertEqual(selected, {
                            "activities_scope": "tomorrow" if activities else None,
                            "include_exams": exams, "exam_scope": "this_week" if exams else None,
                        })

    def test_fresh_exam_data_and_historical_claims_are_transmitted_separately(self):
        selected = context_from_classification({
            "intent": "exam_query", "time_scope": "unspecified", "exam_scope": "upcoming",
            "include_activities": False, "include_exams": True,
        })
        recent = [{"user": "When is my exam?", "assistant": {
            "message": "Earlier we discussed the exam on October 10.", "actions": [],
        }}]
        with patch.object(service, "is_openai_api_key_configured", return_value=True), \
                patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-test-key"}), \
                patch.object(service, "get_agent_model_settings", return_value={"model": "test-model", "reasoning_effort": "none"}), \
                patch.object(service, "select_agent_context", return_value=selected), \
                patch.object(service, "OpenAI") as factory:
            client = factory.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed={
                "message": "Fixture response; no real reasoning is tested.", "actions": [],
            })
            service.get_agent_proposal(self.connection, "What is its current date?", recent)
        request = client.responses.parse.call_args.kwargs
        payload = json.loads(request["input"][-1]["content"])
        latest = next(item for item in payload["observations"]["exams"]["upcoming"] if item["name"] == "Updated exam")
        self.assertEqual(latest["date"], "2026-10-12")
        self.assertIn("October 10", request["input"][1]["content"])
        self.assertIn("trust the latest observations", request["instructions"])
        self.assertIn("proposed_actions_not_executed", request["input"][1]["content"])
        self.assertEqual(payload["clock"]["date"], "2026-10-04")
        client.responses.parse.assert_called_once()


if __name__ == "__main__":
    unittest.main()
