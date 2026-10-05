"""One-shot main-agent recovery; fake model replies, no paid calls or real writes."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.app.ai.agent import reasoning, service
from backend.app.ai.agent.contracts import InvalidProposalError, validate_agent_proposal
from backend.app.ai.agent.context_recovery import (
    MAX_CONTEXT_RECOVERY_RETRIES, build_context_status, recovery_selection,
)


NO_CONTEXT = {"activities_scope": None, "include_exams": False, "exam_scope": None}
TOMORROW = {**NO_CONTEXT, "activities_scope": "tomorrow"}
CLASS = {"count": 1, "upcoming_7d": [{"name": "Physics", "date": "2026-10-05", "start": "09:00", "end": "10:00"}]}
QUERY = {"time_reference": "last_week", "search_terms": ["COMPSCI"]}


def missing(source="activities", scope="tomorrow", **extra):
    return {"message": None, "actions": [], "missing_context": [{"source": source, "time_scope": scope}], **extra}


def answer(message="Your first class is at 09:00.", **extra):
    return {"message": message, "actions": [], **extra}


class ContextManifestTests(unittest.TestCase):
    def test_manifest_distinguishes_not_selected_empty_and_unavailable(self):
        self.assertEqual(build_context_status({}), {
            "current_chat": "provided", "activities": "not_selected",
            "exams": "not_selected", "global_memory": "unavailable",
            "files": "not_selected",
        })
        result = build_context_status({
            "activities": {"count": 0, "today": []},
            "exams": {"status": "unavailable"},
            "memory": {"status": "empty", "items": [], "scope": "global"},
        })
        self.assertEqual(result["activities"], "empty")
        self.assertEqual(result["exams"], "unavailable")
        self.assertEqual(result["global_memory"], "empty")

    def test_truncated_or_untimed_data_is_still_provided(self):
        for observation in (
            {"count": 21, "upcoming_7d": [], "truncated": True},
            {"count": 1, "untimed_count": 1, "today": [{"name": "Assignment", "start": None, "end": None}]},
        ):
            with self.subTest(observation=observation):
                self.assertEqual(build_context_status({"activities": observation})["activities"], "provided")

    def test_current_chat_lookup_does_not_claim_global_memory_was_queried(self):
        result = build_context_status({"memory": {"scope": "current_chat", "status": "ok", "items": [{}]}},
                                      memory_available=True)
        self.assertEqual(result["current_chat"], "provided")
        self.assertEqual(result["global_memory"], "not_selected")

    def test_request_schema_rejects_unknown_sources_scopes_duplicates_and_actions(self):
        invalid = [missing(source=source) for source in
                   ("delete_activity", "global_memory", "current_chat", "screen_time", "/etc/passwd")]
        invalid += [missing(scope="upcoming"), missing(source="exams", scope="all"), missing(scope="year"),
                    {**missing(), "missing_context": missing()["missing_context"] * 3},
                    {**missing(), "missing_context": missing()["missing_context"] * 2},
                    {**missing(), "missing_context": [{"source": "activities", "time_scope": "tomorrow", "sql": "DELETE"}]},
                    answer(message=None)]
        for proposal in invalid:
            with self.subTest(proposal=proposal), self.assertRaises(InvalidProposalError):
                validate_agent_proposal(proposal)
        with self.assertRaises(ValueError):
            recovery_selection(missing()["missing_context"], {"activities": "empty"})


class ContextRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service, "is_openai_api_key_configured", return_value=True))
        self.stack.enter_context(patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-test-key"}))
        self.stack.enter_context(patch.object(service, "get_agent_model_settings", return_value={
            "model": "test-model", "reasoning_effort": "none",
        }))
        self.stack.enter_context(patch.object(service, "get_max_recent_turns", return_value=5))
        self.router = self.stack.enter_context(patch.object(service, "select_agent_context", return_value=NO_CONTEXT))
        self.activities = self.stack.enter_context(patch.object(service, "build_activity_observation", return_value=CLASS))
        self.exams = self.stack.enter_context(patch.object(service, "build_exam_observation", return_value={"count": 1, "upcoming": []}))
        factory = self.stack.enter_context(patch.object(service, "OpenAI"))
        self.client = factory.return_value.__enter__.return_value
        self.connection = Mock()

    def respond(self, *proposals):
        self.client.responses.parse.side_effect = [
            SimpleNamespace(status="completed", output_parsed=proposal) for proposal in proposals
        ]

    def run_agent(self, message="What time should I set my alarm tomorrow?", **kwargs):
        result = service.get_agent_proposal(self.connection, message, [], include_context=True, **kwargs)
        self.connection.execute.assert_not_called()
        self.connection.commit.assert_not_called()
        return result

    def model_input(self, index):
        return json.loads(self.client.responses.parse.call_args_list[index].kwargs["input"][-1]["content"])

    def test_alarm_recovers_once(self):
        self.respond(missing(), answer())
        result = self.run_agent()
        self.assertEqual(result["message"], "Your first class is at 09:00.")
        self.assertEqual(result["missing_context"], [])
        self.router.assert_called_once()
        self.activities.assert_called_once_with(self.connection, scope="tomorrow")
        self.exams.assert_not_called()
        self.assertEqual(self.client.responses.parse.call_count, 2)
        first, second = self.model_input(0), self.model_input(1)
        self.assertEqual(first["observations"], {})
        self.assertEqual(first["context_status"]["activities"], "not_selected")
        self.assertEqual(second["observations"], {"activities": CLASS})
        self.assertEqual(second["context_status"]["activities"], "provided")
        self.assertEqual(second["context_recovery_remaining"], 0)
        self.assertEqual(result["agent_context"]["context_recovery"]["attempts"], MAX_CONTEXT_RECOVERY_RETRIES)

    def test_telemetry_keeps_initial_and_recovered_selection_separate(self):
        self.respond(missing(), answer())
        evidence = {}
        self.run_agent(routing_evidence=evidence)
        self.assertEqual(evidence["initial_selection"], NO_CONTEXT)
        self.assertEqual(evidence["final_selection"], TOMORROW)
        self.assertEqual(evidence["initial_status"]["activities"], "not_selected")
        self.assertEqual(evidence["final_status"]["activities"], "provided")
        self.assertTrue(evidence["recovery_requested"])
        self.assertTrue(evidence["recovery_completed"])
        self.assertNotIn("confirmed", evidence)

    def test_joke_requires_no_recovery(self):
        self.respond(answer("The alarm clock needed a wake-up call."))
        self.run_agent("Tell me a joke about alarm clocks.")
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.activities.assert_not_called()
        self.exams.assert_not_called()

    def test_excluded_calendar_cannot_be_loaded_or_recovered(self):
        # Even a faulty router and a valid-looking model request cannot bypass
        # the user's explicit exclusion at either observation boundary.
        self.router.return_value = {**TOMORROW, "include_exams": True, "exam_scope": "tomorrow"}
        self.respond(missing())
        result = self.run_agent("Don't use my calendar; give general wake-up advice for tomorrow.")
        self.activities.assert_not_called()
        self.exams.assert_not_called()
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(self.model_input(0)["observations"], {})
        self.assertEqual(self.model_input(0)["excluded_sources"], ["activities", "exams"])
        self.assertEqual(result["agent_context"]["context_recovery"]["status"], "rejected")
        self.assertEqual(result["actions"], [])

    def test_excluded_exams_do_not_block_activity_recovery(self):
        self.respond(missing(), answer())
        self.run_agent("Don't show me exams, just tell me my schedule tomorrow.")
        self.activities.assert_called_once_with(self.connection, scope="tomorrow")
        self.exams.assert_not_called()
        self.assertEqual(self.client.responses.parse.call_count, 2)

    def test_provided_empty_and_unavailable_sources_are_not_fetched_again(self):
        for data, expected in ((CLASS, "provided"), ({"count": 0, "today": []}, "empty"),
                               ({"status": "unavailable"}, "unavailable")):
            with self.subTest(status=expected):
                self.router.return_value = TOMORROW
                self.activities.return_value = data
                self.activities.reset_mock()
                self.respond(missing())
                result = self.run_agent()
                self.activities.assert_called_once()
                self.assertEqual(self.client.responses.parse.call_count, 1)
                self.assertEqual(result["agent_context"]["context_status"]["activities"], expected)
                self.assertEqual(result["agent_context"]["context_recovery"]["status"], "rejected")
                self.assertIsNotNone(result["message"])
                self.client.responses.parse.reset_mock()

    def test_selected_schedule_uses_the_normal_single_call_path(self):
        self.router.return_value = TOMORROW
        self.respond(answer())
        result = self.run_agent()
        self.assertEqual(result["agent_context"]["context_status"]["activities"], "provided")
        self.assertEqual(result["agent_context"]["context_recovery"]["attempts"], 0)
        self.activities.assert_called_once()
        self.assertEqual(self.client.responses.parse.call_count, 1)

    def test_unknown_recovery_source_is_rejected_before_any_fetch(self):
        self.respond(missing(source="delete_activity"))
        with self.assertRaises(InvalidProposalError):
            self.run_agent()
        self.activities.assert_not_called()
        self.exams.assert_not_called()
        self.assertEqual(self.client.responses.parse.call_count, 1)

    def test_second_request_cannot_recover_another_source(self):
        self.respond(missing(), missing(source="exams", scope="upcoming"))
        result = self.run_agent()
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.activities.assert_called_once()
        self.exams.assert_not_called()
        self.assertEqual(result["agent_context"]["context_recovery"]["status"], "exhausted")
        self.assertEqual(result["missing_context"], [])
        self.assertEqual(result["actions"], [])

    def test_empty_recovered_source_is_sent_once_as_empty(self):
        self.activities.return_value = {"count": 0, "upcoming_7d": []}
        self.respond(missing(), answer("No classes are scheduled tomorrow."))
        self.run_agent()
        self.activities.assert_called_once()
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.assertEqual(self.model_input(1)["context_status"]["activities"], "empty")

    def test_failed_read_is_unavailable_without_retry_or_private_error_details(self):
        self.activities.side_effect = sqlite3.OperationalError("private-path sk-private-secret")
        self.respond(missing())
        result = self.run_agent()
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(result["agent_context"]["context_status"]["activities"], "unavailable")
        self.assertNotIn("private-path", json.dumps(result))
        self.assertNotIn("sk-private-secret", json.dumps(result))

    def test_recovery_preserves_selected_exams_and_fetches_only_missing_activities(self):
        self.router.return_value = {**NO_CONTEXT, "include_exams": True, "exam_scope": "upcoming"}
        self.respond(missing(), answer())
        self.run_agent()
        self.exams.assert_called_once_with(self.connection, scope="upcoming")
        self.activities.assert_called_once_with(self.connection, scope="tomorrow")
        self.assertEqual(set(self.model_input(1)["observations"]), {"activities", "exams"})

    def test_two_missing_sources_share_one_retry(self):
        request = missing()
        request["missing_context"].append({"source": "exams", "time_scope": "upcoming"})
        self.respond(request, answer())
        self.run_agent()
        self.activities.assert_called_once()
        self.exams.assert_called_once()
        self.assertEqual(self.client.responses.parse.call_count, 2)

    def test_schedule_and_existing_memory_request_share_the_retry(self):
        reader = Mock(return_value={"status": "ok", "items": [{"text": "COMPSCI plan"}], "scope": "global"})
        self.respond(missing(memory_request=QUERY), answer())
        self.run_agent(session_id="authorized-chat", memory_reader=reader)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        reader.assert_called_once()
        self.assertEqual(set(self.model_input(1)["observations"]), {"activities", "memory"})
        self.assertEqual(self.model_input(1)["observations"]["memory"]["followup_lookup_remaining"], 0)

    def test_empty_memory_result_is_reported_on_the_schedule_retry(self):
        reader = Mock(return_value={"status": "empty", "items": [], "scope": "global"})
        self.respond(missing(memory_request=QUERY), answer())
        self.run_agent(session_id="authorized-chat", memory_reader=reader)
        self.assertEqual(self.model_input(1)["context_status"]["global_memory"], "empty")
        self.assertEqual(self.client.responses.parse.call_count, 2)
        reader.assert_called_once()

    def test_memory_retry_cannot_then_trigger_schedule_recovery(self):
        reader = Mock(return_value={"status": "ok", "items": [{"text": "COMPSCI plan"}], "scope": "global"})
        self.respond(answer("Checking history.", memory_request=QUERY), missing())
        self.run_agent(session_id="authorized-chat", memory_reader=reader)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.activities.assert_not_called()
        reader.assert_called_once()

    def test_schedule_retry_cannot_then_trigger_memory_lookup(self):
        reader = Mock()
        self.respond(missing(), answer("Check history too.", memory_request=QUERY))
        self.run_agent(session_id="authorized-chat", memory_reader=reader)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        reader.assert_not_called()

    def test_normal_activity_proposal_keeps_action_arguments_and_does_not_execute(self):
        action = {"tool": "add_activity", "arguments": {
            "name": "Revision", "category": "Study", "subject": "COMPSCI",
            "activity_type": "one_time", "date": "2026-10-05", "weekday": None,
            "start_time": "18:00", "end_time": "19:00",
        }}
        self.respond(answer("This is a proposal only.", actions=[action]))
        result = self.run_agent("Suggest a revision session.")
        self.assertEqual(result["actions"], [action])
        self.assertEqual(self.client.responses.parse.call_count, 1)
        with self.assertRaises(InvalidProposalError):
            validate_agent_proposal({**missing(), "actions": [action]})

    def test_real_activity_builder_is_reused_with_read_only_database(self):
        from backend.app.database import create_tables
        from backend.app.ai.observations.activities import build_activity_observation

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        create_tables(connection)
        connection.execute("INSERT INTO activities (name, category, subject, activity_type, date, start_time, end_time) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("Physics", "Study", "PHYSICS", "one_time", "2026-10-05", "09:00", "10:00"))
        connection.commit()
        connection.execute("PRAGMA query_only=ON")
        self.respond(missing(), answer())
        with patch.object(service, "build_activity_observation", wraps=build_activity_observation) as builder, \
                patch("backend.app.ai.observations.activities.get_current_date", return_value=date(2026, 10, 4)), \
                patch("backend.app.planner.calendar.get_current_date", return_value=date(2026, 10, 4)):
            result = service.get_agent_proposal(connection, "What time should I set my alarm tomorrow?", [])
        builder.assert_called_once_with(connection, scope="tomorrow")
        self.assertEqual(self.model_input(1)["observations"]["activities"]["upcoming_7d"][0]["name"], "Physics")
        self.assertEqual(connection.execute("SELECT count(*) FROM activities").fetchone()[0], 1)
        self.assertEqual(result["missing_context"], [])

    def test_conversation_stores_only_the_final_reply(self):
        from backend.app import database
        from backend.app.conversations import service as conversations

        self.respond(missing(), answer())
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(database, "db_file", Path(directory) / "fixture.sqlite"), \
                patch.object(conversations, "is_openai_api_key_configured", return_value=True):
            chat = conversations.create_chat("fixture-owner")["conversation_id"]
            result = conversations.send_message("fixture-owner", chat, str(uuid4()),
                                                "What time should I set my alarm tomorrow?")
            messages = conversations.read_chat("fixture-owner", chat)["messages"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["content"], "Your first class is at 09:00.")
        self.assertEqual(messages[1]["proposal"]["missing_context"], [])
        self.assertEqual(self.client.responses.parse.call_count, 2)


if __name__ == "__main__":
    unittest.main()
