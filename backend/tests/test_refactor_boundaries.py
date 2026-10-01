"""Offline architecture checks alongside the existing behavioral tests."""

import subprocess
import sys
import unittest
from pathlib import Path
from backend.tests.paths import BACKEND_DIRECTORY, PROJECT_DIRECTORY
from unittest.mock import patch

from backend.app import ai_memory
from backend.app.ai.memory import archive_store, recent, settings


class RefactorBoundaryTests(unittest.TestCase):
    def test_activity_service_has_no_http_or_agent_dependency(self):
        code = """
import sys
sys.modules['fastapi'] = None
sys.modules['backend.app.ai.agent.service'] = None
sys.modules['backend.app.api.ai'] = None
from backend.app import activity_service
assert not hasattr(activity_service, 'HTTPException')
assert not hasattr(activity_service, 'get_agent_proposal')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_reasoning_does_not_import_observations_or_crud(self):
        code = """
import sys
sys.modules['backend.app.ai.observations.activities'] = None
sys.modules['backend.app.ai.observations.exams'] = None
sys.modules['backend.app.planner.activities'] = None
sys.modules['backend.app.planner.exams'] = None
sys.modules['backend.app.ai.memory.archive_store'] = None
from backend.app.ai.agent import reasoning
assert not hasattr(reasoning, 'add_activity')
assert reasoning.proposal_request_limits('high') == (5000, 180)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_durable_storage_imports_without_extraction_or_openai(self):
        code = """
import sys
sys.modules['openai'] = None
sys.modules['backend.app.ai.memory.durable'] = None
from backend.app.ai.memory import durable_store
from backend.app.ai.memory.contracts import DurableMemoryStore
assert durable_store.DurableMemoryStore is DurableMemoryStore
assert not hasattr(durable_store, 'OpenAI')
assert not hasattr(durable_store, 'extract_durable_memories')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_category_policy_imports_without_summary_or_llm_review(self):
        code = """
import sys
sys.modules['openai'] = None
sys.modules['backend.app.ai.memory.summary'] = None
sys.modules['backend.app.ai.memory.category_review'] = None
from backend.app.ai.memory.category_policy import _category_rejection
assert _category_rejection('career', {'general'}) is None
assert _category_rejection('canvas_errors', {'general'}) is not None
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_memory_facade_forwards_state_and_configuration(self):
        original = recent._sessions
        replacement = {}
        with patch.object(ai_memory, "_sessions", replacement):
            self.assertIs(recent._sessions, replacement)
            self.assertIs(ai_memory._sessions, recent._sessions)
        self.assertIs(recent._sessions, original)
        with patch.object(ai_memory, "ARCHIVE_TURN_THRESHOLD", 12):
            self.assertEqual(settings.ARCHIVE_TURN_THRESHOLD, 12)
            self.assertFalse(ai_memory.archive_needs_compaction(12))
            self.assertTrue(ai_memory.archive_needs_compaction(13))
        self.assertEqual(settings.ARCHIVE_TURN_THRESHOLD, 100)
        self.assertIs(ai_memory.get_recent_turns, recent.get_recent_turns)
        self.assertIs(ai_memory._iter_archived_turns, archive_store.iter_archived_turns)

    def test_archive_storage_does_not_import_recent_sessions_or_agent(self):
        code = """
import sys
sys.modules['openai'] = None
sys.modules['backend.app.ai.memory.recent'] = None
sys.modules['backend.app.ai_proposal'] = None
from backend.app.ai.memory import archive_store
assert 'backend.app.ai.memory.selection' not in sys.modules
assert not hasattr(archive_store, '_sessions')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=PROJECT_DIRECTORY,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
