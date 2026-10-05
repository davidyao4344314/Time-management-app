"""File selection/recovery tests: fake Responses calls, never paid requests."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.app import database
from backend.app.ai.agent import service, reasoning
from backend.app.ai.agent.contracts import AgentProposal, InvalidProposalError, validate_agent_proposal
from backend.app.ai.agent.context_recovery import build_context_status, recovery_selection
from backend.app.ai.context import selection as routing
from backend.app.ai.context.contracts import AgentIntentClassification, AgentRoutingDecision, ContextSelection
from backend.app.ai.context.intent import context_from_classification
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.files import storage
from backend.app.files.ingestion import ingest_file
from backend.app.files.retrieval import detect_file_reference, retrieve_file_context

NO_CONTEXT = {"activities_scope": None, "include_exams": False, "exam_scope": None}
ANSWER = {"message": "Question 4 uses recursion; see assignment2.txt.", "actions": []}
NEED_FILE = {"message": None, "actions": [], "missing_context": [{"source": "files", "query": "recursion assignment"}]}
FILE_CLASSIFICATION = {"intent": "general_question", "time_scope": "unspecified",
                       "include_activities": False, "include_exams": False,
                       "files": {"query": "recursion assignment"}}


def response(value):
    return SimpleNamespace(status="completed", output_parsed=value)


class FileRoutingTests(unittest.TestCase):
    def test_explicit_filename_bypasses_semantic_calls_and_keeps_mixed_schedule_intent(self):
        reference = {"selection": {"file_ids": ["file_" + "a" * 32]}, "method": "exact_filename"}
        client = Mock()
        result = routing.select_agent_context(client, "Explain assignment2.pdf", [], "model", file_reference=reference)
        self.assertEqual(result["files"]["file_ids"], reference["selection"]["file_ids"])
        self.assertIsNone(result["activities_scope"])
        client.responses.parse.assert_not_called()
        mixed = routing.select_agent_context(client, "Use assignment2.pdf to plan study tonight", [], "model", file_reference=reference)
        self.assertEqual(mixed["activities_scope"], "today")
        self.assertTrue(mixed["include_exams"])

    def test_semantic_and_fallback_can_request_files_without_receiving_file_text(self):
        for stage in (2, 3):
            client = Mock()
            classified = AgentIntentClassification(**FILE_CLASSIFICATION, confidence="high" if stage == 2 else "low")
            client.responses.parse.side_effect = [response(classified), response(AgentRoutingDecision(**FILE_CLASSIFICATION))]
            trace = {}
            selected = routing.select_agent_context(client, "What was that assignment I uploaded about recursion?", [], "model", trace=trace)
            self.assertEqual(trace["stage"], f"stage_{stage}")
            self.assertEqual(selected["files"]["query"], "recursion assignment")
            for call in client.responses.parse.call_args_list:
                self.assertNotIn("observations", json.loads(call.kwargs["input"][-1]["content"]))
                self.assertNotIn("chunks", json.dumps(call.kwargs["input"]))

    def test_schema_exclusion_status_and_unselected_reader(self):
        reader = Mock()
        collect_agent_observations(None, NO_CONTEXT, file_reader=reader)
        reader.assert_not_called()
        classified = AgentIntentClassification(**FILE_CLASSIFICATION, confidence="high")
        with patch.object(routing, "classify_agent_intent", return_value=classified):
            selected = routing.select_agent_context(Mock(), "Don't use my files; explain recursion generally.", [], "model")
        self.assertNotIn("files", selected)
        self.assertEqual(build_context_status({})["files"], "not_selected")
        self.assertEqual(build_context_status({"files": {"count": 0}})["files"], "empty")
        self.assertEqual(build_context_status({"files": {"status": "unavailable", "count": 0}})["files"], "unavailable")
        self.assertEqual(context_from_classification(classified)["files"]["query"], "recursion assignment")
        for query in ("../secret", "/etc/passwd", "x" * 301):
            with self.assertRaises(ValueError):
                ContextSelection.model_validate({**NO_CONTEXT, "files": {"query": query}})
            with self.assertRaises(InvalidProposalError):
                validate_agent_proposal({**NEED_FILE, "missing_context": [{"source": "files", "query": query}]})
        with self.assertRaises(ValueError):
            recovery_selection(NEED_FILE["missing_context"], {"files": "empty"})
        with self.assertRaises(ValueError):
            recovery_selection(NEED_FILE["missing_context"], {"files": "not_selected"}, excluded_sources={"files"})

    def test_sdk_strict_schema_has_no_arbitrary_tool_or_path_fields(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(AgentProposal)
        self.assertFalse(schema["additionalProperties"])
        request = schema["$defs"]["MissingFileContextRequest"]
        self.assertEqual(request["properties"]["source"]["const"], "files")
        self.assertEqual(request["required"], ["source", "query"])
        self.assertNotIn("path", request["properties"])


class FileAgentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service, "is_openai_api_key_configured", return_value=True))
        self.stack.enter_context(patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-test-key"}))
        self.stack.enter_context(patch.object(service, "get_agent_model_settings", return_value={"model": "test-model", "reasoning_effort": "none"}))
        factory = self.stack.enter_context(patch.object(service, "OpenAI"))
        self.client = factory.return_value.__enter__.return_value
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        storage.migrate(self.connection)
        self.file = ingest_file(self.connection, "owner", "assignment2.txt", b"PRIVATE EXCERPT: question 4 requires recursion.")
        self.connection.execute("PRAGMA query_only=ON")
        self.reader = Mock(side_effect=lambda selected: retrieve_file_context(self.connection, "owner", selected))

    def run_agent(self, message, **kwargs):
        return service.get_agent_proposal(self.connection, message, [], include_context=True, file_reader=self.reader, **kwargs)

    def input(self, index):
        return json.loads(self.client.responses.parse.call_args_list[index].kwargs["input"][-1]["content"])

    def test_exact_reference_sends_only_file_observation_and_private_text_not_inspector(self):
        self.client.responses.parse.return_value = response(ANSWER)
        detector = lambda message: detect_file_reference(self.connection, "owner", message)
        result = self.run_agent("What does assignment2.txt say?", file_detector=detector)
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(set(self.input(0)["observations"]), {"files"})
        public = result["agent_context"]
        self.assertEqual(public["context_status"]["files"], "provided")
        self.assertEqual(public["file_refs"], [self.file["file_id"]])
        self.assertEqual(public["file_context"]["detection"], "exact_filename")
        self.assertNotIn("PRIVATE EXCERPT", json.dumps(public))
        self.assertNotIn("text", public["file_context"]["files"][0])

    def test_file_recovery_uses_existing_single_shared_retry(self):
        self.client.responses.parse.side_effect = [response(NEED_FILE), response(ANSWER)]
        with patch.object(service, "select_agent_context", return_value=NO_CONTEXT.copy()):
            result = self.run_agent("Explain the assignment.")
        self.reader.assert_called_once()
        self.assertEqual(self.input(0)["context_status"]["files"], "not_selected")
        self.assertEqual(self.input(1)["context_status"]["files"], "provided")
        self.assertEqual(self.input(1)["context_recovery_remaining"], 0)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.assertEqual(result["agent_context"]["context_recovery"]["attempts"], 1)

    def test_unrelated_exam_request_does_not_retrieve_file_content(self):
        self.client.responses.parse.return_value = response({"message": "Here is the exam context.", "actions": []})
        with patch.object(service, "build_exam_observation", return_value={"count": 0, "upcoming": []}):
            self.run_agent("What exams do I have this week?", file_detector=lambda message: detect_file_reference(self.connection, "owner", message))
        self.reader.assert_not_called()
        self.assertEqual(set(self.input(0)["observations"]), {"exams"})
        self.assertEqual(self.client.responses.parse.call_count, 1)

    def test_file_recovery_cannot_then_request_schedule_or_memory(self):
        self.client.responses.parse.side_effect = [response(NEED_FILE), response({"message": None, "actions": [],
            "missing_context": [{"source": "activities", "time_scope": "today"}]})]
        with patch.object(service, "select_agent_context", return_value=NO_CONTEXT.copy()):
            result = self.run_agent("Explain the assignment.")
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.assertEqual(result["agent_context"]["context_recovery"]["status"], "exhausted")
        self.assertEqual(result["actions"], [])

    def test_missing_file_unavailable_and_unrelated_requests_are_safe(self):
        self.client.responses.parse.return_value = response({"message": "Please upload that file.", "actions": []})
        detector = lambda message: detect_file_reference(self.connection, "owner", message)
        result = self.run_agent("What does missing.pdf say?", file_detector=detector)
        self.assertEqual(result["agent_context"]["context_status"]["files"], "empty")
        self.reader.reset_mock()
        with patch.object(service, "select_agent_context", return_value=NO_CONTEXT.copy()):
            self.run_agent("Tell me a joke.", file_detector=detector)
        self.reader.assert_not_called()
        self.reader.side_effect = sqlite3.OperationalError("private-path-and-key")
        result = self.run_agent("Read assignment2.txt", file_detector=detector)
        self.assertEqual(result["agent_context"]["context_status"]["files"], "unavailable")
        self.assertNotIn("private-path-and-key", json.dumps(result))

    def test_conversation_keeps_reference_not_document_text_and_followup_resolves(self):
        from backend.app.conversations import service as chats
        from backend.app.conversations.context import build_chat_context
        self.client.responses.parse.return_value = response(ANSWER)
        with tempfile.TemporaryDirectory() as folder, patch.object(database, "db_file", Path(folder) / "test.db"), \
                patch.object(chats, "is_openai_api_key_configured", return_value=True):
            chat = chats.create_chat("owner")["conversation_id"]
            with chats.open_store() as connection:
                saved = ingest_file(connection, "owner", "assignment2.txt", b"PRIVATE EXCERPT: recursion")
            chats.send_message("owner", chat, str(uuid4()), "Explain assignment2.txt")
            with chats.open_store() as connection:
                context = build_chat_context(connection, chat, "owner")
            self.assertEqual(context["file_refs"], [saved["file_id"]])
            self.assertNotIn("PRIVATE EXCERPT", json.dumps(context))
            chats.send_message("owner", chat, str(uuid4()), "Explain that file")
            self.assertEqual(self.input(1)["observations"]["files"]["files"][0]["file_id"], saved["file_id"])


if __name__ == "__main__":
    unittest.main()
