"""Architecture regressions: temporary files and mocked models only."""

import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from backend.app.server import app
from backend.app.api import ai
from backend.app.ai.memory import archive_store, recent, selection, summary, session_identity
from backend.app.ai.memory.compaction_plan import _validate_final_summary
from backend.app.ai.memory.search import search_archived_memory
from backend.app.infrastructure.errors import MemoryUtilityError
from backend.tests.ai.memory.test_ai_archive_persistence import _records, _classified_and_summary


class MemoryBoundaryTests(unittest.TestCase):
    def test_protected_oldest_session_does_not_starve_later_work(self):
        rows = _records(102)
        rows[0]['session_id'] = 'oldest'
        rows[0]['turn']['user'] = 'Remember this: I prefer mornings.'
        for row in rows[1:]:
            row['session_id'] = 'later'
            row['turn']['user'] = 'What is recursion?'
        self.save(rows)
        before = self.path.read_bytes()
        result = selection.select_archive_compaction_candidates()
        self.assertEqual(result['selected_session_id'], 'later')
        self.assertEqual(result['candidate_count'], 50)
        self.assertEqual(self.path.read_bytes(), before)

    def test_many_protected_rows_do_not_hide_later_work_in_same_session(self):
        rows = _records(102)
        for row in rows[:70]:
            row['turn']['user'] = 'Remember this: I prefer mornings.'
        rows[70]['turn']['user'] = 'What is recursion?'
        self.save(rows)
        result = selection.select_archive_compaction_candidates()
        self.assertIn(rows[70], result['compaction_candidates'])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "archive.jsonl"
        for target, name, value in (
            (archive_store, "ARCHIVE_FILE", self.path),
            (recent, "_sessions", {}),
            (recent, "get_max_recent_turns", lambda: 5),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def save(self, rows):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_selection_partitions_sessions_and_keeps_other_rows(self):
        rows = _records(6)
        for index, row in enumerate(rows):
            row["session_id"] = "a" if index % 2 == 0 else "b"
        self.save(rows)
        before = self.path.read_bytes()
        with patch.object(selection.settings, "ARCHIVE_TURN_THRESHOLD", 0):
            selected = selection.select_archive_compaction_candidates(batch_size=5)
        self.assertEqual(selected["compaction_candidates"], rows[::2])
        self.assertEqual(self.path.read_bytes(), before)

    def test_mixed_summary_rejected_before_model_and_persistence(self):
        rows = _records(2)
        rows[1]["session_id"] = "other"
        entries, result = _classified_and_summary(rows)
        with patch.object(summary, "OpenAI") as model:
            self.assertFalse(summary.summarize_compactable_archive_turns(entries)["success"])
        model.assert_not_called()
        with self.assertRaises(MemoryUtilityError):
            _validate_final_summary(result, entries)

    def test_scoped_reader_excludes_mixed_and_unknown_summaries(self):
        raw = _records(1)[0]
        own = {"record_type": "compressed_summary", "source_turn_refs": [{"session_id": "test-session"}]}
        mixed = {"record_type": "compressed_summary", "source_turn_refs": [
            {"session_id": "test-session"}, {"session_id": "other"}]}
        unknown = {"record_type": "compressed_summary", "source_turn_refs": []}
        self.save([raw, own, mixed, unknown])
        self.assertEqual([row for _, row in archive_store.iter_archive_records(session_id="test-session")], [raw, own])
        self.assertEqual(len(list(archive_store.iter_archive_records())), 4)

    def test_search_reuses_shared_reader(self):
        row = _records(1)[0]
        with patch.object(archive_store, "iter_archived_turns", return_value=iter([(0, row)])) as reader:
            result = search_archived_memory({"time_reference": None, "search_terms": []}, session_id="test-session")
        reader.assert_called_once_with(session_id="test-session")
        self.assertEqual(len(result["retrieved_archive"]), 1)

    def test_snapshot_has_no_writes_and_maintenance_keeps_order(self):
        recent._sessions["a"] = deque({"user": str(i), "assistant": "reply"} for i in range(7))
        with patch.object(recent, "_archive_turn") as append:
            self.assertEqual([t["user"] for t in recent.get_recent_turns("a")], ["2", "3", "4", "5", "6"])
            append.assert_not_called()
        self.assertEqual(len(recent._sessions["a"]), 7)
        recent.enforce_recent_limit("a")
        self.assertEqual([row["turn"]["user"] for _, row in archive_store.iter_archived_turns()], ["0", "1"])
        self.assertEqual(len(recent._sessions["a"]), 5)

    def test_failed_maintenance_does_not_evict(self):
        recent._sessions["a"] = deque({"user": str(i), "assistant": "reply"} for i in range(6))
        with patch.object(archive_store, "append_archived_turn", side_effect=OSError):
            with self.assertRaises(OSError):
                recent.enforce_recent_limit("a")
        self.assertEqual(len(recent._sessions["a"]), 6)

    def test_signed_identity_survives_ram_reset_and_rejects_tampering(self):
        client = TestClient(app)
        with patch.object(ai, "is_openai_api_key_configured", return_value=True), \
                patch.object(ai.sqlite3, "connect", return_value=Mock()), \
                patch.object(ai, "get_agent_proposal", return_value={"message": "Reply", "actions": []}):
            self.assertEqual(client.post("/ai/propose", json={"message": "hello"}).status_code, 200)
            identity = client.cookies.get("ai_agent_session")
            signature = client.cookies.get("ai_agent_session_signature")
            recent._sessions.clear()
            self.assertEqual(client.post("/ai/propose", json={"message": "again"}).status_code, 200)
            self.assertEqual(client.cookies.get("ai_agent_session"), identity)
            other = TestClient(app)
            other.cookies.set("ai_agent_session", identity, domain="testserver.local", path="/")
            self.assertEqual(other.post("/ai/propose", json={"message": "hello"}).status_code, 200)
            self.assertNotEqual(other.cookies.get("ai_agent_session"), identity)
        self.assertTrue(session_identity.valid_session(identity, signature))
        self.assertFalse(session_identity.valid_session("0" * 32, signature))
        self.assertEqual(self.path.with_name(".ai_session_key").stat().st_mode & 0o777, 0o600)

    def test_memory_failure_is_safe_http_error(self):
        with patch.object(ai, "is_openai_api_key_configured", return_value=True), \
                patch.object(ai, "enforce_recent_limit", side_effect=OSError("private contents")), \
                patch.object(ai, "get_agent_proposal") as model:
            response = TestClient(app).post("/ai/propose", json={"message": "hello"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private contents", response.text)
        model.assert_not_called()
