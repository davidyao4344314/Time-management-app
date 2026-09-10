"""Import deduplication tests; only an in-memory database is modified."""
import sqlite3
import unittest
from datetime import date, datetime
from unittest.mock import patch

from backend.app import activities, canvas_import, database, exams, uoa_timetable_import


class ImportDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(database.sql_file.read_text())
        self.addCleanup(self.connection.close)

    def snapshot(self, table):
        return self.connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()

    def test_canvas_duplicates_within_feed_and_on_reimport(self):
        events = [
            {"name": "Lab [COMPSCI 130]", "start": date(2026, 9, 9)},
            {"name": "Exam [PHYSICS 140]", "start": date(2026, 9, 10)},
        ]
        result = canvas_import.sort_out_canvas_events(self.connection, events * 2)
        self.assertEqual(result, {"imported": 2, "duplicates_skipped": 2})
        before = [self.snapshot(table) for table in ("activities", "exams")]
        with patch.object(canvas_import, "add_activity") as add_activity, patch.object(canvas_import, "add_exam") as add_exam:
            result = canvas_import.sort_out_canvas_events(self.connection, events)
            add_activity.assert_not_called()
            add_exam.assert_not_called()
        self.assertEqual(result, {"imported": 0, "duplicates_skipped": 2})
        self.assertEqual(before, [self.snapshot(table) for table in ("activities", "exams")])

    def test_checks_match_all_fields_not_id_or_column_order(self):
        converters = [
            (canvas_import.convert_canvas_event_to_activity, activities.add_activity, activities.activity_exists),
            (canvas_import.convert_canvas_event_to_exam, exams.add_exam, exams.exam_exists),
        ]
        for convert, add, exists in converters:
            with self.subTest(convert=convert.__name__):
                columns, values = convert({"name": "Exam lab", "start": date(2026, 9, 9)})
                add(self.connection, ["id", *columns], [75, *values])
                self.assertTrue(exists(self.connection, columns[::-1], values[::-1]))
                self.assertTrue(exists(self.connection, ["id", *columns], [900, *values]))
                for index in range(len(columns)):
                    if columns[index] == "source":
                        continue  # Source metadata does not change existing duplicate rules.
                    changed = values.copy()
                    changed[index] = "different" if values[index] is not None else ""
                    self.assertFalse(exists(self.connection, columns, changed), columns[index])

    def test_uoa_reimport_uses_aggregated_active_range(self):
        events = [
            {"name": "COMPSCI 130 Lecture", "start": datetime(2026, 7, 20, 10), "end": datetime(2026, 7, 20, 11)},
            {"name": "COMPSCI 130 Lecture", "start": datetime(2026, 10, 19, 10), "end": datetime(2026, 10, 19, 11)},
        ]
        result = uoa_timetable_import.import_uoa_timetable_to_activities(self.connection, events)
        self.assertEqual(result["imported"], 1)
        before = self.snapshot("activities")
        with patch.object(uoa_timetable_import, "add_activity") as add_activity:
            result = uoa_timetable_import.import_uoa_timetable_to_activities(self.connection, events[::-1] * 2)
            add_activity.assert_not_called()
        self.assertEqual(result, {"imported": 0, "skipped": [], "duplicates_skipped": 1})
        self.assertEqual(before, self.snapshot("activities"))
        columns, values = uoa_timetable_import.prepare_uoa_activity_ranges(events)[0][0]
        for index in (8, 9):
            changed = values.copy()
            changed[index] = "2027-01-01"
            self.assertFalse(activities.activity_exists(self.connection, columns, changed))

    def test_new_canvas_date_is_saved_and_unknown_still_skipped(self):
        event = {"name": "Exam", "start": date(2026, 9, 9)}
        canvas_import.sort_out_canvas_events(self.connection, [event])
        result = canvas_import.sort_out_canvas_events(self.connection, [
            event,
            {**event, "start": date(2026, 9, 10)},
            {"name": "Unclassified announcement", "start": date(2026, 9, 9)},
        ])
        self.assertEqual(result, {"imported": 1, "duplicates_skipped": 1})
        self.assertEqual(len(self.snapshot("exams")), 2)
        self.assertEqual(self.snapshot("activities"), [])


if __name__ == "__main__":
    unittest.main()
