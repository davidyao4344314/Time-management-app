"""Proposal validation and API tests; never contact OpenAI or change SQLite."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend import fastapi_test as api
from backend.app import ai_proposal


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
        self.assertFalse(request["store"])
        model_input = json.loads(request["input"][0]["content"])
        self.assertEqual(model_input["request"], "Help me plan tonight")
        self.assertEqual(model_input["observations"], {
            "activities": {"today": []}, "exams": {"upcoming": []},
        })

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
