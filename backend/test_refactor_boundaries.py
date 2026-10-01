"""Offline architecture checks alongside the existing behavioral tests."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import ai_memory
from backend.app.memory import archive_store, recent, settings


class RefactorBoundaryTests(unittest.TestCase):
    def test_category_policy_imports_without_summary_or_llm_review(self):
        code = """
import sys
sys.modules['openai'] = None
sys.modules['backend.app.memory.summary'] = None
sys.modules['backend.app.memory.category_review'] = None
from backend.app.memory.category_policy import _category_rejection
assert _category_rejection('career', {'general'}) is None
assert _category_rejection('canvas_errors', {'general'}) is not None
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[1],
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
sys.modules['backend.app.memory.recent'] = None
sys.modules['backend.app.ai_proposal'] = None
from backend.app.memory import archive_store
assert 'backend.app.memory.selection' not in sys.modules
assert not hasattr(archive_store, '_sessions')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
