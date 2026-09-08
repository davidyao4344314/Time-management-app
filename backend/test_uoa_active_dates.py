"""Run from the project root: backend/.venv/bin/python -m unittest backend.test_uoa_active_dates -v"""
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import calender, database
from backend.app.activities import add_activity, remove_duplicate_activities
from backend.app.uoa_timetable_import import (
    backfill_uoa_activity_ranges,
    convert_uoa_event_to_activity,
    import_uoa_timetable_to_activities,
    prepare_uoa_activity_ranges,
)


def class_event(day, name="COMPSCI 130 Lecture"):
    return {
        "name": name,
        "start": datetime.fromisoformat(f"{day}T10:00:00"),
        "end": datetime.fromisoformat(f"{day}T11:00:00"),
    }


class TimetableDateTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(database.sql_file.read_text())
        self.addCleanup(self.connection.close)

    def test_converter_preserves_local_dates(self):
        event = {
            "name": "COMPSCI 130 Lecture",
            "start": datetime(2026, 7, 19, 22, tzinfo=timezone.utc),
            "end": datetime(2026, 7, 19, 23, tzinfo=timezone.utc),
        }
        columns, values = convert_uoa_event_to_activity(event)
        row = dict(zip(columns, values))
        self.assertEqual(row["weekday"], "Monday")
        self.assertEqual(row["start_time"], "10:00")
        self.assertEqual(row["active_start_date"], "2026-07-20")
        self.assertEqual(row["active_end_date"], "2026-07-20")
        self.assertNotIn("active_start_date", event)

    def test_feed_dates_not_semester_name_determine_range(self):
        events = [class_event("2026-06-01"), class_event("2026-03-02")]
        schedules, skipped = prepare_uoa_activity_ranges(events)
        self.assertEqual(skipped, [])
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0][1][-2:], ["2026-03-02", "2026-06-01"])
        result = import_uoa_timetable_to_activities(self.connection, events)
        self.assertEqual(result["imported"], 1)

    def test_inclusive_weekly_range_and_invalid_ranges(self):
        def occurs(day, start="2026-03-02", end="2026-06-01"):
            return calender.is_activity_on_date("weekly", None, "Monday", date.fromisoformat(day), start, end)
        for day in ["2026-03-02", "2026-03-16", "2026-06-01"]:
            self.assertTrue(occurs(day))
        for day in ["2026-02-23", "2026-03-03", "2026-06-08", "2026-08-03"]:
            self.assertFalse(occurs(day))
        for start, end in [(None, "2026-06-01"), ("", "2026-06-01"), ("bad", "bad"), ("2026-06-01", "2026-03-02")]:
            self.assertFalse(occurs("2026-03-16", start, end))
        self.assertTrue(occurs("2026-08-03", None, None))

    def test_semester_1_vs_semester_2_and_today(self):
        events = [
            class_event("2026-03-02", "First semester class"),
            class_event("2026-06-01", "First semester class"),
            class_event("2026-07-20", "Second semester class"),
            class_event("2026-10-19", "Second semester class"),
        ]
        import_uoa_timetable_to_activities(self.connection, events)
        columns, values = convert_uoa_event_to_activity(class_event("2026-03-02", "Manual weekly"))
        values[1] = "Study"
        values[-2:] = [None, None]
        add_activity(self.connection, columns, values)
        for day, expected in [(date(2026, 3, 16), "First semester class"), (date(2026, 8, 3), "Second semester class")]:
            with patch.object(calender, "get_current_date", return_value=day):
                weekly = calender.get_week_activities(self.connection)
                self.assertEqual({row["name"] for row in weekly}, {expected, "Manual weekly"})
                self.assertEqual({row[1] for row in calender.get_todays_activities(self.connection)}, {expected, "Manual weekly"})

    def test_backfill_preserves_ids_and_nonmatching_manual_rows(self):
        columns, values = convert_uoa_event_to_activity(class_event("2026-03-02"))
        values[-2:] = [None, None]
        add_activity(self.connection, columns, values)
        manual = values.copy()
        manual[0] = "Manual university activity"
        add_activity(self.connection, columns, manual)
        before = self.connection.execute("SELECT * FROM activities").fetchall()
        result = backfill_uoa_activity_ranges(self.connection, [class_event("2026-03-02"), class_event("2026-06-01")])
        after = self.connection.execute("SELECT * FROM activities").fetchall()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["unmatched_ids"], [2])
        self.assertEqual([row[:9] for row in before], [row[:9] for row in after])
        self.assertEqual(after[0][-2:], ("2026-03-02", "2026-06-01"))
        self.assertEqual(after[1][-2:], (None, None))
        self.assertEqual(backfill_uoa_activity_ranges(self.connection, [class_event("2026-03-02")])["updated"], 0)

    def test_cleanup_does_not_merge_different_date_ranges(self):
        for day in ["2026-03-02", "2026-03-02", "2026-07-20"]:
            add_activity(self.connection, *convert_uoa_event_to_activity(class_event(day)))
        self.assertEqual(remove_duplicate_activities(self.connection), 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0], 2)

    def test_migrate_existing_database_preserves_original_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            connection = sqlite3.connect(path)
            # The old schema, including its older NOT NULL time constraint.
            schema = database.sql_file.read_text().replace(",\n    active_start_date TEXT,\n    active_end_date TEXT", "")
            schema = schema.replace("start_time TEXT", "start_time TEXT NOT NULL").replace("end_time TEXT", "end_time TEXT NOT NULL")
            connection.executescript(schema)
            connection.execute("INSERT INTO activities (id,name,category,activity_type,weekday,start_time,end_time) VALUES (20,'Manual','Study','weekly','Monday','10:00','11:00')")
            connection.commit()
            old_row = connection.execute("SELECT * FROM activities").fetchone()
            connection.close()
            with patch.object(database, "db_file", path):
                for _ in range(2):
                    connection = database.create_connection()
                    row = connection.execute("SELECT * FROM activities").fetchone()
                    self.assertEqual(row[:9], old_row)
                    self.assertEqual(row[9:], (None, None))
                    connection.close()


if __name__ == "__main__":
    unittest.main()
