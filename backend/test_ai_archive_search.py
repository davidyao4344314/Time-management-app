"""Offline tests for the bounded, per-session archived-conversation search."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.app import ai_memory
from backend.app.ai_archive_search import resolve_time_reference, search_archived_memory


AUCKLAND = ZoneInfo("Pacific/Auckland")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=AUCKLAND)


def archived_turn(user, assistant, timestamp=None, session_id="session-one"):
    record = {
        "session_id": session_id,
        "turn": {"user": user, "assistant": {"message": assistant, "actions": []}},
    }
    if timestamp is not None:
        record["timestamp"] = timestamp
    return record


class ArchiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.archive_file = Path(self.temporary_directory.name) / "archive.jsonl"
        archive_patch = patch.object(ai_memory, "ARCHIVE_FILE", self.archive_file)
        archive_patch.start()
        self.addCleanup(archive_patch.stop)
        limit_patch = patch.object(ai_memory, "get_max_recent_turns", return_value=5)
        limit_patch.start()
        self.addCleanup(limit_patch.stop)

    def write_archive(self, *records):
        self.archive_file.write_text(
            "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8",
        )

    def search(self, time_reference, search_terms, limit=5):
        return search_archived_memory(
            {"time_reference": time_reference, "search_terms": search_terms},
            session_id="session-one", limit=limit, now=NOW,
        )["retrieved_archive"]

    def test_new_archived_turn_keeps_its_original_completion_timestamp(self):
        completed_at = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        later = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "datetime") as clock:
            clock.now.side_effect = [completed_at] + [later] * 5
            for number in range(1, 7):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            recent = ai_memory.get_recent_turns("session-one")

        archived = json.loads(self.archive_file.read_text().splitlines()[0])
        self.assertEqual(archived["timestamp"], completed_at.isoformat(timespec="seconds"))
        self.assertEqual(archived["turn"]["user"], "Turn 1")
        self.assertNotIn("timestamp", archived["turn"])
        self.assertEqual(len(recent), 5)

    def test_last_week_and_compsci_respects_time_and_session(self):
        self.write_archive(
            archived_turn("COMPSCI study plan", "Revision at 7 PM", "2026-09-23T11:00:00+12:00"),
            archived_turn("COMPSCI this week", "Another plan", "2026-09-30T10:00:00+13:00"),
            archived_turn("MATHS study plan", "Maths revision", "2026-09-24T10:00:00+12:00"),
            archived_turn("COMPSCI private", "Other session", "2026-09-23T10:00:00+12:00", "session-two"),
            archived_turn("COMPSCI undated", "Old record"),
        )
        matches = self.search("last_week", ["COMPSCI", "study plan"])
        self.assertEqual([item["user"] for item in matches], ["COMPSCI study plan", "MATHS study plan"])
        self.assertEqual(matches[0]["timestamp"], "2026-09-23T11:00:00+12:00")
        self.assertNotIn("session-two", str(matches))

    def test_topic_only_search_includes_undated_legacy_record(self):
        self.write_archive(
            archived_turn("We discussed screen time", "Set a daily limit"),
            archived_turn("How are my activities?", "You mentioned Screen Time before", "2026-09-22T09:00:00+12:00"),
            archived_turn("Unrelated", "No relevant topic", "2026-09-23T09:00:00+12:00"),
        )
        matches = self.search(None, ["screen time"])
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["user"], "We discussed screen time")
        self.assertIsNone(matches[0]["timestamp"])

    def test_time_only_search_returns_recent_matching_dates(self):
        self.write_archive(
            archived_turn("Morning plan", "One hour", "2026-09-30T08:00:00+13:00"),
            archived_turn("Evening plan", "Two hours", "2026-09-30T20:00:00+13:00"),
            archived_turn("Today plan", "Three hours", "2026-10-01T08:00:00+13:00"),
            archived_turn("Undated plan", "Unknown date"),
        )
        self.assertEqual(
            [item["user"] for item in self.search("yesterday", [])],
            ["Evening plan", "Morning plan"],
        )

    def test_no_match_or_missing_archive_returns_empty(self):
        self.assertEqual(self.search("last_week", ["COMPSCI"]), [])
        self.write_archive(archived_turn("Maths", "Lecture", "2026-09-23T09:00:00+12:00"))
        self.assertEqual(self.search("last_week", ["COMPSCI"]), [])

    def test_result_limit_is_capped_at_five_and_ranked(self):
        self.write_archive(*[
            archived_turn(f"COMPSCI plan {index}", "COMPSCI revision", f"2026-09-23T{index:02d}:00:00+12:00")
            for index in range(1, 9)
        ])
        self.assertEqual(len(self.search("last_week", ["COMPSCI"], limit=99)), 5)
        self.assertEqual(
            [item["user"] for item in self.search("last_week", ["COMPSCI"], limit=2)],
            ["COMPSCI plan 8", "COMPSCI plan 7"],
        )

    def test_more_user_keyword_matches_outrank_newer_assistant_match(self):
        self.write_archive(
            archived_turn("COMPSCI COMPSCI revision", "Study plan", "2026-09-23T08:00:00+12:00"),
            archived_turn("An unrelated question", "COMPSCI", "2026-09-23T20:00:00+12:00"),
        )
        self.assertEqual(
            [item["user"] for item in self.search("last_week", ["COMPSCI"])],
            ["COMPSCI COMPSCI revision", "An unrelated question"],
        )

    def test_assistant_text_is_searched_and_excerpt_is_short(self):
        self.write_archive(archived_turn(
            "What should I do?", "A" * 700 + " COMPSCI revision", "2026-09-23T09:00:00+12:00",
        ))
        matches = self.search("last_week", ["COMPSCI"])
        self.assertEqual(len(matches), 1)
        self.assertIn("COMPSCI", matches[0]["assistant"])
        self.assertLessEqual(len(matches[0]["assistant"]), 602)

    def test_symbolic_boundaries_include_calendar_month_and_week(self):
        last_week = resolve_time_reference("last_week", now=NOW)
        this_month = resolve_time_reference("this_month", now=NOW)
        last_month = resolve_time_reference("last_month", now=NOW)
        self.assertEqual(last_week[0].date().isoformat(), "2026-09-21")
        self.assertEqual(last_week[1].date().isoformat(), "2026-09-28")
        self.assertEqual(last_month[0].date().isoformat(), "2026-09-01")
        self.assertEqual(last_month[1].date().isoformat(), "2026-10-01")
        self.assertEqual(this_month[0].date().isoformat(), "2026-10-01")
        self.assertEqual(this_month[1].date().isoformat(), "2026-11-01")
        self.assertEqual(resolve_time_reference("unspecified", now=NOW), (None, None))

    def test_session_id_is_required(self):
        with self.assertRaises(ValueError):
            search_archived_memory(
                {"time_reference": None, "search_terms": ["COMPSCI"]},
                session_id="", now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
