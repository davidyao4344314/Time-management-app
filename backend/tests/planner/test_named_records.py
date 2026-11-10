import sqlite3
import unittest
from contextlib import closing

from backend.app.api.common import activity_to_dict
from backend.app.planner.activities import get_activity_by_id, get_activities_by_name
from backend.app.planner.exams import exam_to_dict, get_all_exams


class NamedRecordTests(unittest.TestCase):
    def test_activity_lookup_uses_column_names_and_keeps_tuple_compatibility(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript("""
                CREATE TABLE activities (name TEXT, weekday TEXT, start_time TEXT,
                    end_time TEXT, activity_type TEXT, category TEXT, date TEXT,
                    subject TEXT, id INTEGER PRIMARY KEY, unrelated TEXT);
                INSERT INTO activities VALUES ('Study', 'Monday', '09:00', '10:00',
                    'weekly', 'School', NULL, 'Maths', 7, 'not an API field');
            """)
            activity = get_activity_by_id(connection, 7)
            self.assertEqual(get_activities_by_name(connection, "Study"), [activity])
            self.assertEqual(activity[0], activity.id)
            result = activity_to_dict(activity)
            self.assertEqual(result["start_time"], "09:00")
            self.assertEqual(result["weekday"], "Monday")
            self.assertEqual(result["source"], "Manual")
            self.assertNotIn("unrelated", result)
            self.assertIsNone(get_activity_by_id(connection, 999))

    def test_exam_lookup_works_with_a_reordered_schema(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript("""
                CREATE TABLE exams (date TEXT, name TEXT, subject TEXT, end_time TEXT,
                    start_time TEXT, category TEXT, id INTEGER PRIMARY KEY, source TEXT);
                INSERT INTO exams VALUES ('2026-11-20', 'Final', 'Maths', NULL, NULL,
                    'Exam', 9, 'Canvas');
            """)
            [exam] = get_all_exams(connection)
            result = exam_to_dict(exam)
            self.assertEqual((result["id"], result["date"], result["source"]),
                             (9, "2026-11-20", "Canvas"))
            self.assertIsNone(result["external_id"])
            self.assertIsNone(result["start_time"])
