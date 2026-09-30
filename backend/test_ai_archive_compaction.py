"""Offline checks for the archive turn-count threshold (no compaction)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import ai_memory


class ArchiveCompactionThresholdTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.archive_file = Path(temporary_directory.name) / "archive.jsonl"
        archive_patch = patch.object(ai_memory, "ARCHIVE_FILE", self.archive_file)
        archive_patch.start()
        self.addCleanup(archive_patch.stop)

    def write_turns(self, count):
        self.archive_file.write_text(
            "".join(
                json.dumps({
                    "session_id": "test-session",
                    "turn": {"user": f"Turn {number}", "assistant": "Reply"},
                }) + "\n"
                for number in range(1, count + 1)
            ),
            encoding="utf-8",
        )

    def test_threshold_boundaries_and_archive_counts(self):
        self.assertEqual(ai_memory.ARCHIVE_TURN_THRESHOLD, 100)
        self.assertEqual(ai_memory.ARCHIVE_COMPACT_BATCH, 50)
        self.assertEqual(ai_memory.get_archive_turn_count(), 0)

        for count in (0, 50, 99, 100, 101, 150):
            with self.subTest(count=count):
                self.write_turns(count)
                self.assertEqual(ai_memory.get_archive_turn_count(), count)
                self.assertEqual(
                    ai_memory.archive_needs_compaction(count), count > 100,
                )

    def test_threshold_constant_can_be_configured(self):
        with patch.object(ai_memory, "ARCHIVE_TURN_THRESHOLD", 2):
            self.assertFalse(ai_memory.archive_needs_compaction(2))
            self.assertTrue(ai_memory.archive_needs_compaction(3))

    def test_archiving_checks_threshold_without_changing_archive_or_recent_turns(self):
        self.write_turns(100)
        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "get_max_recent_turns", return_value=5), \
                patch.object(ai_memory, "_logger") as logger:
            for number in range(1, 7):
                ai_memory.add_completed_turn(
                    "new-session", f"New turn {number}",
                    {"message": f"Response {number}", "actions": []},
                )
            recent = ai_memory.get_recent_turns("new-session")

        records = [json.loads(line) for line in self.archive_file.read_text().splitlines()]
        self.assertEqual(len(records), 101)
        self.assertEqual(records[0]["turn"]["user"], "Turn 1")
        self.assertEqual(records[-1]["turn"]["user"], "New turn 1")
        self.assertEqual(
            [turn["user"] for turn in recent],
            [f"New turn {number}" for number in range(2, 7)],
        )
        logger.warning.assert_called_once_with(
            "Archive compaction required: %d archived turns.", 101,
        )


if __name__ == "__main__":
    unittest.main()
