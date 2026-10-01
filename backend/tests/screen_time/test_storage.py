"""Screen Time checks use disposable in-memory SQLite only."""
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from backend.app.database import create_tables
from backend.app.screen_time import storage
from backend.app.ai.observations import screen_time as observations


class ScreenTimeStorageTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        create_tables(self.connection)
        self.addCleanup(self.connection.close)

    def test_insert_and_read_summary(self):
        record_id = storage.add_screen_time(self.connection, "2026-09-25", 310, 90, 125, 60, 35)
        self.assertEqual(storage.get_screen_time_by_date(self.connection, "2026-09-25"), {
            "id": record_id, "date": "2026-09-25", "total_minutes": 310,
            "productive_minutes": 90, "social_minutes": 125,
            "entertainment_minutes": 60, "other_minutes": 35,
        })

    def test_same_date_updates_instead_of_creating_another_row(self):
        first = storage.add_screen_time(self.connection, "2026-09-25", 310)
        second = storage.add_screen_time(self.connection, "2026-09-25", 250)
        self.assertEqual(first, second)
        self.assertEqual(storage.get_screen_time_by_date(
            self.connection, "2026-09-25")["total_minutes"], 250)
        self.assertEqual(len(storage.get_screen_time_range(
            self.connection, "2026-09-01", "2026-09-30")), 1)

    def test_range_is_inclusive_and_sorted(self):
        for day in ("2026-09-27", "2026-09-25", "2026-09-26"):
            storage.add_screen_time(self.connection, day)
        rows = storage.get_screen_time_range(self.connection, "2026-09-25", "2026-09-26")
        self.assertEqual([row["date"] for row in rows], ["2026-09-25", "2026-09-26"])
        self.assertIsNone(rows[0]["total_minutes"])
        self.assertIsNone(storage.get_screen_time_by_date(self.connection, "2026-09-24"))

    def test_invalid_input_is_rejected(self):
        for day in ("invalid", "2026-02-30", "20260925", None):
            with self.subTest(day=day), self.assertRaises(ValueError):
                storage.add_screen_time(self.connection, day)
        for minutes in (-1, True, "30"):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                storage.add_screen_time(self.connection, "2026-09-25", minutes)
        with self.assertRaises(ValueError):
            storage.get_screen_time_range(self.connection, "2026-09-26", "2026-09-25")

    def test_observation_still_handles_nullable_minutes(self):
        storage.add_screen_time(self.connection, "2026-09-24", 100, None, 40)
        storage.add_screen_time(self.connection, "2026-09-25", 200, 60, None)
        with patch.object(observations, "date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 25)
            result = observations.build_screen_time_observation(self.connection, days=2)
        self.assertEqual(result["recorded_days"], 2)
        self.assertEqual(result["avg_total_min"], 150)
        self.assertEqual(result["avg_productive_min"], 60)
        self.assertEqual(result["avg_social_min"], 40)
        self.assertIsNone(result["avg_entertainment_min"])
        self.assertEqual(result["highest_total_day"], "2026-09-25")

    def test_legacy_package_exports_the_same_functions(self):
        from backend.app import screen_time
        self.assertIs(screen_time.add_screen_time, storage.add_screen_time)
        self.assertIs(screen_time.get_screen_time_range, storage.get_screen_time_range)


if __name__ == "__main__":
    unittest.main()
