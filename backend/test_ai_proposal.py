"""Proposal validation and API tests; never contact OpenAI or change SQLite."""

import json
import sqlite3
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from fastapi.testclient import TestClient

from backend import fastapi_test as api
from backend.app import (
    activity_observation, ai_context_router, ai_memory, ai_proposal,
    exam_observation,
)


def activity_action(**changes):
    arguments = {
        "name": "COMPSCI revision",
        "category": "Study",
        "subject": "COMPSCI 130",
        "activity_type": "one_time",
        "date": "2026-09-26",
        "weekday": None,
        "start_time": "18:00",
        "end_time": "19:00",
    }
    arguments.update(changes)
    return {"tool": "add_activity", "arguments": arguments}


class AIProposalTests(unittest.TestCase):
    def test_context_router_examples(self):
        cases = (
            ("What should I do today?", "today", False, None),
            ("What should I study tonight?", "today", True, "upcoming"),
            ("What do I have this week?", "week", False, None),
            ("What am I doing this month?", "month", False, None),
            ("What exams do I have?", None, True, "upcoming"),
            ("What exams do I have this month?", None, True, "month"),
            ("Show me all activities.", "all", False, None),
            ("Look at all my activities and exams.", "all", True, "upcoming"),
            ("What should I do today for my exams?", "today", True, "upcoming"),
            ("Everything on my calendar", "all", False, None),
            ("Show my full calendar", "all", False, None),
            ("Show my entire schedule", "all", False, None),
            ("Look at everything", "all", True, "upcoming"),
            ("What are my upcoming quizzes?", None, True, "upcoming"),
            ("What is coming in the next few days?", "week", False, None),
            ("What is due later this month?", "month", False, None),
            ("TODAY’S schedule", "today", False, None),
            ("Help me plan", "today", True, "upcoming"),
        )
        for message, activity_scope, include_exams, exam_scope in cases:
            with self.subTest(message=message):
                self.assertEqual(ai_context_router.choose_agent_context(message), {
                    "activities_scope": activity_scope,
                    "include_exams": include_exams,
                    "exam_scope": exam_scope,
                })

    def test_today_observation_does_not_send_later_dates(self):
        today = date(2026, 9, 29)
        occurrence = {
            "id": 1, "name": "Lecture", "start_time": "11:00",
            "end_time": "12:00", "calendar_date": "2026-09-29",
        }
        tomorrow = {**occurrence, "calendar_date": "2026-09-30"}
        connection = Mock()
        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", return_value=[occurrence, tomorrow]) as week:
            result = activity_observation.build_activity_observation(connection, scope="today")

        week.assert_called_once_with(connection, today)
        self.assertEqual(result["today"], [{"name": "Lecture", "start": "11:00", "end": "12:00"}])
        self.assertNotIn("upcoming_7d", result)

    def test_week_observation_uses_the_next_seven_dates(self):
        today = date(2026, 9, 29)
        occurrence = {
            "id": 1, "name": "Study", "start_time": None, "end_time": None,
            "calendar_date": "2026-10-05",
        }
        too_late = {**occurrence, "calendar_date": "2026-10-06"}
        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", return_value=[occurrence, too_late]):
            result = activity_observation.build_activity_observation(Mock(), scope="week")
        self.assertEqual(result["upcoming_7d"], [
            {"name": "Study", "date": "2026-10-05", "start": None, "end": None},
        ])

    def test_month_observation_uses_calendar_recurrence_and_stops_at_month_end(self):
        today = date(2026, 9, 1)
        starts = []

        def calendar_occurrences(_connection, week_start):
            starts.append(week_start)
            if week_start == date(2026, 9, 29):
                return [
                    {"id": 1, "name": "Month end", "calendar_date": "2026-09-30",
                     "start_time": None, "end_time": None},
                    {"id": 2, "name": "Next month", "calendar_date": "2026-10-01",
                     "start_time": None, "end_time": None},
                ]
            return []

        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", side_effect=calendar_occurrences):
            result = activity_observation.build_activity_observation(Mock(), scope="month")

        self.assertEqual(starts, [date(2026, 9, day) for day in (1, 8, 15, 22, 29)])
        self.assertEqual(result["upcoming_month"], [
            {"name": "Month end", "date": "2026-09-30", "start": None, "end": None},
        ])

    def test_month_observation_uses_real_calendar_recurrence_rules(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("""
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY, name TEXT, category TEXT, subject TEXT,
                activity_type TEXT, date TEXT, weekday TEXT, start_time TEXT,
                end_time TEXT, active_start_date TEXT, active_end_date TEXT
            )
        """)
        connection.executemany(
            """INSERT INTO activities
               (name, category, activity_type, date, weekday, start_time, end_time)
               VALUES (?, 'Study', ?, ?, ?, NULL, NULL)""",
            [
                ("Daily", "daily", None, None),
                ("Weekly", "weekly", None, "Wednesday"),
                ("September task", "one_time", "2026-09-30", None),
                ("October task", "one_time", "2026-10-01", None),
            ],
        )
        with patch.object(activity_observation, "get_current_date", return_value=date(2026, 9, 29)), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)):
            result = activity_observation.build_activity_observation(connection, scope="month")

        self.assertEqual(
            [(item["name"], item["date"]) for item in result["upcoming_month"]],
            [
                ("Daily", "2026-09-29"),
                ("Daily", "2026-09-30"),
                ("September task", "2026-09-30"),
                ("Weekly", "2026-09-30"),
            ],
        )

    def test_all_activity_scope_uses_existing_activity_rows(self):
        activity = (1, "Lecture", "University", "COMPSCI 130", "weekly",
                    None, "Monday", "10:00", "11:00", "2026-07-01", "2026-11-01")
        with patch.object(activity_observation, "get_all_activities", return_value=[activity]), \
                patch.object(activity_observation, "get_week_activities") as week:
            result = activity_observation.build_activity_observation(Mock(), scope="all")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["all_activities"][0]["weekday"], "Monday")
        self.assertEqual(result["all_activities"][0]["active_end_date"], "2026-11-01")
        week.assert_not_called()

    def test_exam_month_scope_uses_same_date_boundaries(self):
        exams = [
            (1, "September test", "Test", "COMPSCI", "2026-09-30", None, None),
            (2, "October test", "Test", "COMPSCI", "2026-10-01", None, None),
        ]
        with patch.object(exam_observation, "get_current_date", return_value=date(2026, 9, 29)), \
                patch.object(exam_observation, "get_current_time", return_value="09:00"), \
                patch.object(exam_observation, "get_all_exams", return_value=exams):
            result = exam_observation.build_exam_observation(Mock(), scope="month")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["upcoming"][0]["date"], "2026-09-30")

    def test_request_builds_only_selected_observations(self):
        cases = (
            ("What do I have this week?", "week", None),
            ("What exams do I have this month?", None, "month"),
            ("Look at all my activities and exams.", "all", "upcoming"),
        )
        for message, activity_scope, exam_scope in cases:
            with self.subTest(message=message), \
                    patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                    patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                    patch.object(ai_proposal, "build_activity_observation", return_value={"activity_data": True}) as activity_builder, \
                    patch.object(ai_proposal, "build_exam_observation", return_value={"exam_data": True}) as exam_builder, \
                    patch.object(ai_proposal, "OpenAI") as client_class:
                client = client_class.return_value.__enter__.return_value
                client.responses.parse.return_value = SimpleNamespace(
                    status="completed", output_parsed={"message": "Reply", "actions": []},
                )
                ai_proposal.get_agent_proposal(Mock(), message)
                payload = json.loads(client.responses.parse.call_args.kwargs["input"][-1]["content"])
                if activity_scope is None:
                    activity_builder.assert_not_called()
                    self.assertNotIn("activities", payload["observations"])
                else:
                    activity_builder.assert_called_once_with(ANY, scope=activity_scope)
                    self.assertIn("activities", payload["observations"])
                if exam_scope is None:
                    exam_builder.assert_not_called()
                    self.assertNotIn("exams", payload["observations"])
                else:
                    exam_builder.assert_called_once_with(ANY, scope=exam_scope)
                    self.assertIn("exams", payload["observations"])

    def test_only_the_last_five_completed_turns_are_kept(self):
        with patch.object(ai_memory, "_sessions", {}):
            for number in range(1, 6):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            first_five = ai_memory.get_recent_turns("session-one")
            self.assertEqual([turn["user"] for turn in first_five],
                             [f"Turn {number}" for number in range(1, 6)])
            self.assertEqual(first_five[0]["assistant"]["message"], "Reply 1")

            ai_memory.add_completed_turn(
                "session-one", "Turn 6", {"message": "Reply 6", "actions": []},
            )
            latest_five = ai_memory.get_recent_turns("session-one")
            self.assertEqual([turn["user"] for turn in latest_five],
                             [f"Turn {number}" for number in range(2, 7)])
            self.assertEqual([turn["assistant"]["message"] for turn in latest_five],
                             [f"Reply {number}" for number in range(2, 7)])

    def test_message_only_is_valid(self):
        result = ai_proposal.validate_agent_proposal({
            "message": "No extra study session is needed.",
            "actions": [],
        })
        self.assertEqual(result.model_dump()["actions"], [])

    def test_add_activity_proposal_is_valid(self):
        result = ai_proposal.validate_agent_proposal({
            "message": "I suggest a revision session.",
            "actions": [activity_action()],
        })
        self.assertEqual(result.actions[0].arguments.date, "2026-09-26")

    def test_daily_and_weekly_proposals_are_valid(self):
        for action in (
            activity_action(activity_type="daily", date=None, weekday=None),
            activity_action(activity_type="weekly", date=None, weekday="Monday"),
        ):
            with self.subTest(activity_type=action["arguments"]["activity_type"]):
                result = ai_proposal.validate_agent_proposal({
                    "message": "I suggest this activity.", "actions": [action],
                })
                self.assertEqual(result.actions[0].arguments.activity_type,
                                 action["arguments"]["activity_type"])

    def test_unknown_tools_and_bad_activity_data_are_rejected(self):
        invalid_actions = [
            {**activity_action(), "tool": "delete_activity"},
            {**activity_action(), "tool": "add_exam"},
            activity_action(date="2026-02-30"),
            activity_action(start_time="25:00"),
            activity_action(start_time="19:00", end_time="18:00"),
            activity_action(activity_type="weekly", date=None, weekday="Funday"),
            activity_action(activity_type="daily", date="2026-09-26"),
            activity_action(name=" "),
            {**activity_action(), "arguments": {**activity_action()["arguments"], "sql": "DELETE"}},
        ]
        for action in invalid_actions:
            with self.subTest(action=action):
                with self.assertRaises(ai_proposal.InvalidProposalError):
                    ai_proposal.validate_agent_proposal({"message": "Plan", "actions": [action]})

    def test_missing_fields_and_empty_message_are_rejected(self):
        with self.assertRaises(ai_proposal.InvalidProposalError):
            ai_proposal.validate_agent_proposal({"message": " ", "actions": []})
        incomplete = activity_action()
        del incomplete["arguments"]["category"]
        with self.assertRaises(ai_proposal.InvalidProposalError):
            ai_proposal.validate_agent_proposal({"message": "Plan", "actions": [incomplete]})

    def test_model_receives_separate_observations_and_returns_proposal(self):
        expected = {"message": "No change needed.", "actions": []}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value={"today": []}), \
                patch.object(ai_proposal, "build_exam_observation", return_value={"upcoming": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed=expected,
            )
            result = ai_proposal.get_agent_proposal(Mock(), "Help me plan tonight")
            request = client.responses.parse.call_args.kwargs

        self.assertEqual(result, expected)
        self.assertEqual(request["text_format"], ai_proposal.AgentProposal)
        self.assertEqual(request["instructions"], ai_proposal.STUDY_PLANNING_INSTRUCTIONS)
        self.assertFalse(request["store"])
        model_input = json.loads(request["input"][0]["content"])
        self.assertEqual(model_input["request"], "Help me plan tonight")
        self.assertEqual(model_input["observations"], {
            "activities": {"today": []}, "exams": {"upcoming": []},
        })

    def test_follow_up_receives_both_sides_of_the_turn_and_fresh_observations(self):
        history = [{
            "user": "Help me study tonight.",
            "assistant": {
                "message": "I suggest COMPSCI from 7–8 PM.",
                "actions": [activity_action(start_time="19:00", end_time="20:00")],
            },
        }]
        updated_observations = {"today": [], "upcoming_7d": []}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value=updated_observations), \
                patch.object(ai_proposal, "build_exam_observation", return_value={"upcoming": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={"message": "What later time works?", "actions": []},
            )
            ai_proposal.get_agent_proposal(Mock(), "Make it later.", history)
            messages = client.responses.parse.call_args.kwargs["input"]

        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[0]["content"], "Help me study tonight.")
        earlier_reply = json.loads(messages[1]["content"])
        self.assertEqual(earlier_reply["message"], "I suggest COMPSCI from 7–8 PM.")
        self.assertEqual(earlier_reply["proposed_actions_not_executed"][0]["arguments"]["start_time"], "19:00")
        latest_request = json.loads(messages[2]["content"])
        self.assertEqual(latest_request["request"], "Make it later.")
        self.assertEqual(latest_request["observations"]["activities"], updated_observations)
        self.assertIn("trust the latest observations", ai_proposal.STUDY_PLANNING_INSTRUCTIONS)

    def test_endpoint_session_keeps_five_completed_turns(self):
        connection = Mock()
        client = TestClient(api.app)
        histories = []

        def mock_proposal(_connection, message, recent_turns):
            histories.append(list(recent_turns))
            return {"message": f"Reply to {message}", "actions": []}

        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=connection), \
                patch.object(api, "get_agent_proposal", side_effect=mock_proposal), \
                patch.object(api, "add_activity") as insert:
            for number in range(1, 7):
                response = client.post("/ai/propose", json={"message": f"Turn {number}"})
                self.assertEqual(response.status_code, 200)
                if number == 1:
                    self.assertIn("httponly", response.headers["set-cookie"].lower())
            session_id = client.cookies.get("ai_agent_session")
            stored = ai_memory.get_recent_turns(session_id)
            response = client.post("/ai/propose", json={"message": "Turn 7"})
            self.assertEqual(response.status_code, 200)

        self.assertEqual([len(history) for history in histories], [0, 1, 2, 3, 4, 5, 5])
        self.assertEqual([turn["user"] for turn in stored],
                         [f"Turn {number}" for number in range(2, 7)])
        self.assertEqual(stored[-1]["assistant"]["message"], "Reply to Turn 6")
        self.assertEqual([turn["user"] for turn in histories[-1]],
                         [f"Turn {number}" for number in range(2, 7)])
        insert.assert_not_called()
        self.assertEqual(connection.close.call_count, 7)

    def test_failed_proposal_does_not_create_a_completed_turn(self):
        client = TestClient(api.app)
        with patch.object(ai_memory, "_sessions", {}) as sessions, \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=Mock()), \
                patch.object(api, "get_agent_proposal", side_effect=ai_proposal.InvalidProposalError):
            response = client.post("/ai/propose", json={"message": "Plan tonight"})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(sessions, {})
            self.assertNotIn("ai_agent_session", client.cookies)

    def test_separate_browser_sessions_do_not_share_history(self):
        histories = []

        def mock_proposal(_connection, _message, recent_turns):
            histories.append(recent_turns)
            return {"message": "Reply", "actions": []}

        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=Mock()), \
                patch.object(api, "get_agent_proposal", side_effect=mock_proposal):
            first_client = TestClient(api.app)
            second_client = TestClient(api.app)
            first_client.post("/ai/propose", json={"message": "First user's plan"})
            second_client.post("/ai/propose", json={"message": "Second user's plan"})

        self.assertEqual(histories, [[], []])
        self.assertNotEqual(first_client.cookies.get("ai_agent_session"),
                            second_client.cookies.get("ai_agent_session"))

    def test_instructions_keep_advice_and_actions_separate(self):
        instructions = ai_proposal.STUDY_PLANNING_INSTRUCTIONS
        for rule in (
            "study planning assistant",
            "activity and exam observations",
            "ask one simple follow-up question",
            "user-facing message",
            "separate actions list",
            "only allowed tool is add_activity",
            "Never execute a tool, generate SQL",
            '"message": "response for the user", "actions": []',
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, instructions)

    def test_missing_key_prevents_model_call(self):
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=False), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                ai_proposal.get_agent_proposal(Mock(), "Plan tonight")
            client_class.assert_not_called()

    def test_endpoint_returns_proposal_without_inserting(self):
        expected = {"message": "I suggest revision.", "actions": [activity_action()]}
        connection = Mock()
        with patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=connection) as connect, \
                patch.object(api, "get_agent_proposal", return_value=expected), \
                patch.object(api, "add_activity") as insert:
            response = TestClient(api.app).post(
                "/ai/propose", json={"message": "Plan two hours tonight"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertTrue(connect.call_args.kwargs["uri"])
        self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))
        connection.close.assert_called_once()
        insert.assert_not_called()

    def test_endpoint_rejects_missing_key_without_reading_database(self):
        with patch.object(api, "is_openai_api_key_configured", return_value=False), \
                patch.object(api.sqlite3, "connect") as connect:
            response = TestClient(api.app).post(
                "/ai/propose", json={"message": "Plan tonight"},
            )
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
