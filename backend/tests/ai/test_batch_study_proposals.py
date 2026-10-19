"""Bounded multi-subject planning with fresh read-only calendar evidence."""

import json
import sqlite3
import unittest
from contextlib import ExitStack
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import database
from backend.app.ai.agent import service, reasoning, schedule_guard
from backend.app.ai.observations.proposal_schedule import build_proposal_schedule_observation
from backend.app.ai.actions.activity_tool import describe_activity_proposals
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.routing import prepare_tool_proposals
from backend.app.infrastructure.clock import LOCAL_TIMEZONE
from backend.tests.ai.test_llm_action_proposals import native_batch


def future_batch(day="2026-10-31", hour=8):
    response = native_batch()
    for index, call in enumerate(response.output):
        fields = json.loads(call.arguments)
        fields.update(date=day, start_time=f"{hour + index:02d}:00", end_time=f"{hour + index + 1:02d}:00")
        call.arguments = json.dumps(fields)
    return response


class ScheduleGuardTests(unittest.TestCase):
    def test_history_and_all_definitions_cannot_establish_availability(self):
        proposal = reasoning.parse_agent_response(future_batch())
        for data in ({}, {"activities": {"all_activities": [], "count": 0}},
                     {"activities": {"status": "unavailable"}}):
            self.assertEqual(schedule_guard.unchecked_proposal_dates(proposal, data), [date(2026, 10, 31)])

    def test_sparse_dates_do_not_claim_coverage_of_other_days(self):
        proposal = reasoning.parse_agent_response(future_batch())
        self.assertEqual(schedule_guard.unchecked_proposal_dates(proposal, {"activities": {
            "checked_dates": ["2026-10-30", "2026-11-01"], "count": 0}}), [date(2026, 10, 31)])
        self.assertEqual(schedule_guard.unchecked_proposal_dates(proposal, {"activities": {
            "period": {"start": "2026-10-14", "end": "2026-10-31"}, "count": 0}}), [])

    def test_recurring_dates_use_existing_weekday_logic_and_date_only_is_safe(self):
        proposal = reasoning.parse_agent_response(future_batch())
        fields = proposal["actions"][0]["arguments"]
        fields.update(activity_type="weekly", date=None, weekday="Monday")
        proposal["actions"] = proposal["actions"][:1]
        with patch.object(schedule_guard, "local_now", return_value=datetime(2026, 10, 14, tzinfo=LOCAL_TIMEZONE)):
            self.assertEqual(schedule_guard.proposal_schedule_dates(proposal), [date(2026, 10, 19)])
            fields.update(activity_type="daily", weekday=None)
            self.assertEqual(len(schedule_guard.proposal_schedule_dates(proposal)), 7)
        fields.update(start_time=None, end_time=None)
        self.assertEqual(schedule_guard.proposal_schedule_dates(proposal), [])


class FreshCalendarProposalTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        database.create_tables(self.connection)
        self.connection.execute("INSERT INTO activities (name, category, activity_type, date, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
                                ("Existing lecture", "University", "one_time", "2026-10-31", "08:00", "12:00"))
        self.connection.commit()
        self.connection.execute("PRAGMA query_only=ON")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for patcher in (
            patch.object(service, "is_openai_api_key_configured", return_value=True),
            patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-only-key"}),
            patch.object(service, "get_agent_model_settings", return_value={"model": "offline-model", "reasoning_effort": "none"}),
            patch.object(service, "get_max_recent_turns", return_value=5),
        ):
            self.stack.enter_context(patcher)
        self.route = self.stack.enter_context(patch.object(service, "select_agent_context", return_value={
            "activities_scope": None, "include_exams": False, "exam_scope": None}))
        factory = self.stack.enter_context(patch.object(service, "OpenAI"))
        self.model = factory.return_value.__enter__.return_value.responses.parse
        self.model.side_effect = [future_batch(), future_batch(hour=14)]

    def run_agent(self, message="Not only Physics; add study sessions for all four exams.", history=None):
        return service.get_agent_proposal(self.connection, message, history or [], include_context=True)

    def payload(self, index):
        return json.loads(self.model.call_args_list[index].kwargs["input"][-1]["content"])

    def test_unselected_calendar_is_read_for_draft_dates_before_final_proposals(self):
        history = [{"user": "Plan exam study.", "assistant": {"message": "That morning looks free.", "actions": []}}]
        result = self.run_agent(history=history)
        self.assertEqual(len(result["actions"]), 4)
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(self.payload(1)["observations"]["activities"]["busy"], {"2026-10-31": [["08:00", "12:00"]]})
        self.assertEqual(self.payload(1)["context_recovery_remaining"], 0)
        self.assertEqual(result["actions"][0]["arguments"]["start_time"], "14:00")
        source = next(item for item in result["agent_context"]["context_sources"] if item["source"] == "activities")
        self.assertTrue(source["selected"])
        self.assertIn("2026-10-31", source["reason"])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM activities").fetchone()[0], 1)

    def test_already_covered_dates_need_no_extra_model_call(self):
        self.route.return_value["activities_scope"] = "month"
        self.model.side_effect = [future_batch(hour=14)]
        observation = {"count": 1, "period": {"start": "2026-10-14", "end": "2026-10-31"}, "busy": {"2026-10-31": [["08:00", "12:00"]]}}
        with patch.object(service, "build_activity_observation", return_value=observation), \
                patch.object(service, "build_proposal_schedule_observation") as read:
            self.assertEqual(len(self.run_agent()["actions"]), 4)
        read.assert_not_called()
        self.assertEqual(self.model.call_count, 1)

    def test_partial_initial_coverage_rechecks_entire_batch(self):
        self.route.return_value["activities_scope"] = "today"
        first = future_batch()
        fields = json.loads(first.output[0].arguments)
        fields["date"] = "2026-10-14"
        first.output[0].arguments = json.dumps(fields)
        self.model.side_effect = [first, first]
        with patch.object(service, "build_activity_observation", return_value={"count": 0, "period": {"start": "2026-10-14", "end": "2026-10-14"}}):
            result = self.run_agent()
        self.assertEqual(self.payload(1)["observations"]["activities"]["checked_dates"], ["2026-10-14", "2026-10-31"])
        self.assertEqual(len(result["actions"]), 4)

    def test_exclusions_and_read_failures_never_publish_unchecked_proposals(self):
        with patch.object(service, "build_proposal_schedule_observation") as read:
            result = self.run_agent("Do not use my calendar; add study sessions.")
        read.assert_not_called()
        self.assertEqual(result["actions"], [])
        self.assertEqual(self.model.call_count, 1)
        self.model.reset_mock()
        self.model.side_effect = [future_batch()]
        with patch.object(service, "build_proposal_schedule_observation", side_effect=sqlite3.OperationalError("private-path secret")):
            result = self.run_agent()
        self.assertEqual(result["actions"], [])
        self.assertEqual(self.model.call_count, 1)
        self.assertNotIn("private-path", json.dumps(result))

    def test_second_draft_cannot_move_to_an_unchecked_date_or_make_third_call(self):
        self.model.side_effect = [future_batch(), future_batch(day="2026-11-01")]
        result = self.run_agent()
        self.assertEqual(result["actions"], [])
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(result["agent_context"]["context_recovery"]["status"], "exhausted")

    def test_calendar_read_is_bounded_reuses_recurrence_and_preserves_data(self):
        result = build_proposal_schedule_observation(self.connection, [date(2026, 10, 31), date(2026, 11, 1)])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["busy"], {"2026-10-31": [["08:00", "12:00"]]})
        for days in ([], ["2026-10-31"], [date(2026, 10, 14)] * 18):
            with self.subTest(days=days), self.assertRaises(ValueError):
                build_proposal_schedule_observation(self.connection, days)
        self.assertEqual(self.connection.total_changes, 1)

    def test_existing_overlap_is_visible_as_warning_without_blocking_proposal(self):
        proposals = prepare_tool_proposals(reasoning.parse_agent_response(future_batch())["actions"], create_proposal_tool_registry())
        reviewed = describe_activity_proposals(self.connection, proposals)
        self.assertEqual(len(reviewed), 4)
        self.assertTrue(all("Warning: overlaps" in item.display_description for item in reviewed))
        self.assertTrue(all("Existing lecture" in item.display_description for item in reviewed))
        self.assertTrue(all(item.status.value == "pending_approval" for item in reviewed))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
