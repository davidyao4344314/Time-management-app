"""Offline checks for archive thresholds and read-only candidate selection."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def write_turns(self, count, *, timestamped=False):
        first_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.archive_file.write_text(
            "".join(
                json.dumps({
                    **({"timestamp": (first_time + timedelta(minutes=number)).isoformat()}
                       if timestamped else {}),
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

    def test_selection_boundaries_and_batch_size(self):
        for count, expected_candidates in ((0, 0), (50, 0), (100, 0),
                                           (101, 50), (150, 50)):
            with self.subTest(count=count):
                self.write_turns(count, timestamped=True)
                original_archive = self.archive_file.read_bytes()
                result = ai_memory.select_archive_compaction_candidates()
                self.assertEqual(result["needs_compaction"], count > 100)
                self.assertEqual(result["archive_turn_count"], count)
                self.assertEqual(result["candidate_count"], expected_candidates)
                self.assertEqual(result["remaining_turn_count"], count - expected_candidates)
                self.assertEqual(
                    [row["turn"]["user"] for row in result["compaction_candidates"]],
                    [f"Turn {number}" for number in range(1, expected_candidates + 1)],
                )
                self.assertEqual(self.archive_file.read_bytes(), original_archive)

        self.write_turns(101, timestamped=True)
        result = ai_memory.select_archive_compaction_candidates(batch_size=200)
        self.assertEqual(result["candidate_count"], 101)
        self.assertEqual(result["remaining_turn_count"], 0)

    def test_selection_uses_timestamps_not_append_order(self):
        self.write_turns(101, timestamped=True)
        rows = [json.loads(line) for line in self.archive_file.read_text().splitlines()]
        rows[0]["timestamp"] = "2027-01-01T00:00:00+00:00"
        self.archive_file.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
        )

        with patch.object(ai_memory, "_sessions", {
            "test-session": [{"user": "Recent only", "assistant": "Reply"}],
        }):
            result = ai_memory.select_archive_compaction_candidates()

        names = [row["turn"]["user"] for row in result["compaction_candidates"]]
        self.assertEqual(names, [f"Turn {number}" for number in range(2, 52)])
        self.assertNotIn("Recent only", names)
        self.assertEqual(result["oldest_candidate_timestamp"], "2026-01-01T00:02:00+00:00")
        self.assertEqual(result["newest_candidate_timestamp"], "2026-01-01T00:51:00+00:00")

    def test_undated_legacy_turns_use_archive_order_without_fake_timestamps(self):
        self.write_turns(101)
        result = ai_memory.select_archive_compaction_candidates()
        self.assertEqual(
            [row["turn"]["user"] for row in result["compaction_candidates"]],
            [f"Turn {number}" for number in range(1, 51)],
        )
        self.assertIsNone(result["oldest_candidate_timestamp"])
        self.assertIsNone(result["newest_candidate_timestamp"])

    def test_invalid_batch_size_is_rejected(self):
        for batch_size in (-1, True, "50"):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                ai_memory.select_archive_compaction_candidates(batch_size=batch_size)


if __name__ == "__main__":
    unittest.main()
