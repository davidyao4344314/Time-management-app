"""Native model requests -> pending review -> explicit execution, all offline."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai.lib._parsing._responses import parse_response
from openai.types.responses import Response, ResponseFunctionToolCall

from backend.app import database
from backend.app.api import actions, action_runtime, conversations
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.service import ActionProposalService
from backend.app.ai.agent import reasoning, service as agent
from backend.app.ai.agent.contracts import AgentProposal, InvalidProposalError
from backend.app.ai.agent.tool_calls import public_agent_tools
from backend.app.conversations import service as chats
from backend.app.infrastructure import identity


ARGUMENTS = {"name": "COMPSCI revision", "category": "Study", "subject": "COMPSCI 130",
             "activity_type": "one_time", "date": "2026-10-07", "weekday": None,
             "start_time": "18:00", "end_time": "19:00"}


def native_response(*, name="add_activity", arguments=None, text=None, **call_fields):
    call = SimpleNamespace(type="function_call", name=name,
                           arguments=json.dumps(ARGUMENTS if arguments is None else arguments),
                           call_id="provider-call-id", status="completed")
    for key, value in call_fields.items():
        setattr(call, key, value)
    return SimpleNamespace(status="completed", output=[call], output_parsed=text)


class NativeToolRequestTests(unittest.TestCase):
    def test_only_schema_is_public_and_tool_choice_is_optional(self):
        tools = public_agent_tools()
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], "add_activity")
        self.assertEqual(set(tool), {"type", "name", "description", "parameters", "strict"})
        self.assertEqual(set(tool["parameters"]["properties"]), set(ARGUMENTS))
        self.assertEqual(set(tool["parameters"]["required"]), set(ARGUMENTS))
        self.assertFalse(tool["parameters"]["additionalProperties"])
        self.assertTrue(tool["strict"])
        self.assertIsNone(create_proposal_tool_registry().resolve("add_activity").handler)
        client = Mock()
        reasoning.request_agent_response(client, "Hello", {}, [],
                                         {"model": "test-model", "reasoning_effort": "none"}, 1200)
        request = client.responses.parse.call_args.kwargs
        self.assertEqual(request["tools"], tools)
        self.assertEqual(request["tool_choice"], "auto")
        self.assertFalse(request["parallel_tool_calls"])
        self.assertFalse(request["store"])

    def test_normal_reply_and_tool_only_and_mixed_reply(self):
        advice = {"message": "No changes needed.", "actions": []}
        normal = reasoning.parse_agent_response(SimpleNamespace(status="completed", output=[], output_parsed=advice))
        self.assertEqual(normal["actions"], [])
        tool_only = reasoning.parse_agent_response(native_response())
        self.assertIn("Nothing is saved", tool_only["message"])
        self.assertEqual(tool_only["actions"], [{"tool": "add_activity", "arguments": ARGUMENTS}])
        mixed = reasoning.parse_agent_response(native_response(text=advice))
        self.assertEqual(mixed["message"], advice["message"])
        self.assertEqual(mixed["actions"], tool_only["actions"])

    def test_invalid_unknown_or_tampered_calls_are_controlled(self):
        invalid = [native_response(name="delete_activity"), native_response(arguments={}),
                   native_response(arguments={**ARGUMENTS, "status": "approved"}),
                   native_response(arguments={**ARGUMENTS, "external_id": "model-controlled"}),
                   native_response(arguments={**ARGUMENTS, "date": "2026-02-30"}),
                   native_response(arguments={**ARGUMENTS, "end_time": "17:00"}),
                   native_response(arguments=[ARGUMENTS]), native_response(arguments="not an object"),
                   native_response(status="in_progress"), native_response(call_id=""),
                   native_response(text={"message": "Need context", "actions": [],
                                         "memory_request": {"time_reference": "yesterday", "search_terms": []}})]
        broken_json = native_response()
        broken_json.output[0].arguments = "private-malformed-payload"
        invalid.append(broken_json)
        multiple = native_response()
        multiple.output *= 2
        invalid.append(multiple)
        for response in invalid:
            with self.subTest(response=response), self.assertRaises(InvalidProposalError) as raised:
                reasoning.parse_agent_response(response)
            self.assertNotIn("private-malformed-payload", str(raised.exception))

    def test_text_actions_cannot_substitute_for_native_calls(self):
        for output in ([], native_response().output):
            with self.subTest(output=output), self.assertRaises(InvalidProposalError):
                reasoning.parse_agent_response(SimpleNamespace(status="completed", output=output,
                    output_parsed={"message": "Saved!", "actions": [{"tool": "add_activity", "arguments": ARGUMENTS}]}))
        fake_text = '{"tool":"add_activity","arguments":{}}'
        result = reasoning.parse_agent_response(SimpleNamespace(status="completed", output=[],
            output_parsed={"message": fake_text, "actions": []}))
        self.assertEqual(result["actions"], [])

    def test_sdk_native_call_is_parsed_without_a_text_response(self):
        for status in (None, "completed"):
            with self.subTest(status=status):
                raw = Response.model_construct(status="completed", output=[ResponseFunctionToolCall(
                    type="function_call", name="add_activity", arguments=json.dumps(ARGUMENTS),
                    call_id="sdk-call", status=status)])
                parsed = parse_response(response=raw, input_tools=public_agent_tools(), text_format=AgentProposal)
                self.assertIsNone(parsed.output_parsed)
                self.assertEqual(reasoning.parse_agent_response(parsed)["actions"][0]["arguments"], ARGUMENTS)

    def test_sdk_parse_failure_is_sanitized(self):
        client = Mock()
        client.responses.parse.side_effect = ValueError("private raw arguments")
        with self.assertRaises(InvalidProposalError) as raised:
            reasoning.request_agent_response(client, "Hello", {}, [],
                                             {"model": "test-model", "reasoning_effort": "none"}, 1200)
        self.assertNotIn("private raw", str(raised.exception))


class ModelChatApprovalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.path = Path(directory.name) / "test.db"
        with closing(sqlite3.connect(self.path)) as connection:
            database.create_tables(connection)
        self.stack.enter_context(patch.object(database, "db_file", self.path))
        self.stack.enter_context(patch.object(identity, "IDENTITY_KEY_FILE", Path(directory.name) / "key"))
        self.stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "offline-placeholder", "ACTION_LAYER_DEV_MODE": "0"}))
        self.stack.enter_context(patch.object(chats, "is_openai_api_key_configured", return_value=True))
        self.stack.enter_context(patch.object(agent, "is_openai_api_key_configured", return_value=True))
        self.stack.enter_context(patch.object(agent, "get_agent_model_settings", return_value={"model": "test-model", "reasoning_effort": "none"}))
        self.stack.enter_context(patch.object(agent, "select_agent_context", return_value={"activities_scope": None, "include_exams": False, "exam_scope": None}))
        factory = self.stack.enter_context(patch.object(agent, "OpenAI"))
        self.model = factory.return_value.__enter__.return_value.responses.parse
        self.model.return_value = native_response()
        self.stack.enter_context(patch.object(action_runtime, "service", ActionProposalService(action_runtime.execution_resources)))
        self.connect = self.stack.enter_context(patch.object(action_runtime.common, "create_connection", side_effect=lambda: sqlite3.connect(self.path)))
        app = FastAPI()
        app.include_router(conversations.router)
        app.include_router(actions.router)
        self.client, self.other = TestClient(app), TestClient(app)
        self.chat = self.client.post("/conversations", json={}).json()["conversation_id"]
        self.request = {"request_id": str(uuid4()), "message": "Add COMPSCI revision tomorrow."}

    def send(self):
        return self.client.post(f"/conversations/{self.chat}/messages", json=self.request)

    def proposals(self):
        return self.client.get("/actions/proposals").json()["proposals"]

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT * FROM activities").fetchall()

    def test_model_request_waits_for_confirmation_then_creates_once(self):
        self.assertEqual(self.send().status_code, 200)
        view = self.proposals()[0]
        self.assertEqual(view["status"], "pending_approval")
        self.assertTrue(view["requires_approval"])
        self.assertNotEqual(view["id"], "provider-call-id")
        self.assertIn("COMPSCI revision", view["display_description"])
        self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()
        # Replays/refreshes return saved chat; never regenerate pending authority.
        self.assertEqual(self.send().status_code, 200)
        self.client.get(f"/conversations/{self.chat}/messages")
        self.assertEqual(self.proposals(), [view])
        self.model.assert_called_once()
        self.assertEqual(self.other.get("/actions/proposals").json()["proposals"], [])
        decision_path = f"/actions/proposals/{view['id']}/decision"
        self.assertEqual(self.other.post(decision_path, json={"decision": "confirm"}).status_code, 404)
        saved = self.client.post(decision_path, json={"decision": "confirm"})
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["result"]["success"])
        self.assertEqual(saved.json()["status"], "completed")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0][1], ARGUMENTS["name"])
        self.assertEqual(self.client.post(decision_path, json={"decision": "confirm"}).status_code, 409)
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.proposals()), 1)
        self.connect.assert_called_once()
        self.model.assert_called_once()  # No post-execution model continuation.

    def test_cancel_never_opens_execution_resources(self):
        self.assertEqual(self.send().status_code, 200)
        view = self.proposals()[0]
        result = self.client.post(f"/actions/proposals/{view['id']}/decision", json={"decision": "cancel"})
        self.assertEqual(result.json()["status"], "rejected")
        self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()

    def test_context_recovery_registers_only_the_final_tool_request(self):
        self.model.side_effect = [SimpleNamespace(status="completed", output=[], output_parsed={
            "message": None, "actions": [],
            "missing_context": [{"source": "activities", "time_scope": "today"}]}), native_response()]
        with patch.object(agent, "build_activity_observation", return_value={"count": 0, "today": []}):
            self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(len(self.proposals()), 1)
        self.assertEqual(self.proposals()[0]["status"], "pending_approval")
        self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()

    def test_chat_persistence_failure_never_registers_pending_authority(self):
        with patch.object(chats.storage, "complete_request", side_effect=sqlite3.OperationalError("offline failure")):
            self.assertEqual(self.send().status_code, 500)
        self.assertEqual(self.proposals(), [])
        self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()

    def test_normal_chat_does_not_create_a_proposal(self):
        self.model.return_value = SimpleNamespace(status="completed", output=[], output_parsed={"message": "Hello!", "actions": []})
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.proposals(), [])
        self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()

    def test_invalid_model_request_is_502_without_proposals_or_activity_writes(self):
        for response in (native_response(name="delete_activity"), native_response(arguments={}),
                         native_response(arguments={**ARGUMENTS, "approved": True})):
            with self.subTest(response=response):
                self.request["request_id"] = str(uuid4())
                self.model.return_value = response
                failed = self.send()
                self.assertEqual(failed.status_code, 502)
                self.assertEqual(self.proposals(), [])
                self.assertEqual(self.rows(), [])
        self.connect.assert_not_called()

    def test_restart_does_not_recreate_old_authority_from_saved_chat(self):
        self.assertEqual(self.send().status_code, 200)
        action_runtime.service = ActionProposalService(action_runtime.execution_resources)
        self.assertEqual(self.send().status_code, 200)
        self.client.get(f"/conversations/{self.chat}/messages")
        self.assertEqual(self.proposals(), [])
        self.assertEqual(self.rows(), [])
        self.model.assert_called_once()
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
