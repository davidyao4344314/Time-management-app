import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.app import database
from backend.app.conversations import service
from backend.app.ai.context import selection
from backend.app.ai.context.contracts import AgentIntentClassification, AgentRoutingDecision
from backend.app.ai.context.adaptive import store
from backend.app.ai.context.adaptive.settings import AdaptiveSettings
from backend.tests.ai.test_adaptive_store import EMPTY


class AdaptiveEvidenceTests(unittest.TestCase):
    def test_all_stage_candidates_are_recorded_without_confirming_them(self):
        evidence = {}
        decision = dict(intent="general_question", time_scope="unspecified", include_activities=False, include_exams=False)
        with patch.object(selection, "assess_stage_one", return_value={"selection": EMPTY, "confident": False}), \
                patch.object(selection, "classify_agent_intent", return_value=AgentIntentClassification(**decision, confidence="low")), \
                patch.object(selection, "classify_stage_three", return_value=AgentRoutingDecision(**decision)):
            result = selection.select_agent_context(Mock(), "Tell me something", [], "test-model", evidence=evidence)
        self.assertEqual(result, EMPTY)
        self.assertEqual([item["stage"] for item in evidence["candidates"]], ["stage_1", "stage_2", "stage_3"])
        self.assertNotIn("confirmed", evidence)

    def test_completed_request_records_once_and_learning_failure_keeps_answer(self):
        def fake_agent(*args, routing_evidence, **kwargs):
            routing_evidence.update(classifier_model="test-model", initial_selection=EMPTY,
                                    final_selection=EMPTY, initial_status={}, final_status={})
            return {"message": "A fixture reply.", "actions": []}

        for fail in (False, True):
            with self.subTest(failure=fail), tempfile.TemporaryDirectory() as directory, \
                    patch.object(database, "db_file", Path(directory) / "test.db"), \
                    patch.object(service, "is_openai_api_key_configured", return_value=True), \
                    patch.object(service, "get_adaptive_settings", return_value=AdaptiveSettings(mode="observe")), \
                    patch.object(service, "get_agent_proposal", side_effect=fake_agent) as model:
                chat = service.create_chat("owner")["conversation_id"]
                request = str(uuid4())
                if fail:
                    with patch.object(store, "record_event", side_effect=sqlite3.OperationalError("fixture failure")):
                        result = service.send_message("owner", chat, request, "Question")
                    self.assertTrue(result["routing_learning_pending"])
                else:
                    service.send_message("owner", chat, request, "Question")
                    with service.open_store() as connection:
                        records = store.load_eligible_evidence(connection, "owner", chat)
                        self.assertEqual(len(records), 1)
                        self.assertIsNone(records[0]["label"])
                retry = service.send_message("owner", chat, request, "Question")
                self.assertEqual(retry["status"], "completed")
                self.assertEqual(model.call_count, 1)
