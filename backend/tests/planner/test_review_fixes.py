"""Planner boundary regressions using in-memory SQLite only."""

import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from backend.app import database
from backend.app.planner import activities, activity_service, calendar, exams, exam_service
from backend.tests.planner.test_activity_service import activity_fields


class PlannerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(database.sql_file.read_text())

    def test_partial_edit_failure_rolls_back_every_field(self):
        row = activity_service.create_activity_record(self.connection,
            activity_service.prepare_new_activity(activity_fields()))
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise sqlite3.OperationalError("simulated write failure")
            return activities.edit_activity(*args, **kwargs)

        with patch.object(activity_service, "edit_activity", side_effect=fail_second):
            with self.assertRaises(sqlite3.OperationalError):
                activity_service.update_activity_record(self.connection, row[0], {
                    "activity_id": row[0], "column_name": "activity_type",
                    "new_value": "weekly", "weekday": "Monday"})
        self.assertEqual(activities.get_activity_by_id(self.connection, row[0]), row)
        self.assertFalse(self.connection.in_transaction)

    def test_edit_preserves_callers_transaction(self):
        row = activity_service.create_activity_record(self.connection,
            activity_service.prepare_new_activity(activity_fields()))
        self.connection.execute("BEGIN")
        activity_service.update_activity_record(self.connection, row[0], {
            "activity_id": row[0], "column_name": "name", "new_value": "Changed"})
        self.assertTrue(self.connection.in_transaction)
        self.connection.rollback()
        self.assertEqual(activities.get_activity_by_id(self.connection, row[0]), row)
        activities.edit_activity(self.connection, row[0], "name", "Standalone")
        self.assertFalse(self.connection.in_transaction)

    def test_exam_service_and_calendar_composition_preserve_fields(self):
        columns, values = exam_service.prepare_new_exam({
            "name": " Test ", "category": "Assessment", "subject": "Physics",
            "date": "2026-10-01", "start_time": None, "end_time": None})
        exams.add_exam(self.connection, columns, values)
        row = exams.get_all_exams(self.connection)[0]
        updated = exam_service.update_exam_record(self.connection, row[0], {
            "exam_id": row[0], "column_name": "name", "new_value": "Updated test"})
        self.assertEqual(updated[1], "Updated test")
        self.assertEqual(updated[7:], row[7:])
        self.assertEqual(calendar.get_calendar_week(self.connection, date(2026, 9, 28)), [])
        items = calendar.get_calendar_week(self.connection, date(2026, 9, 28), include_exams=True)
        self.assertEqual(items, [{**exams.exam_to_dict(updated), "event_type": "exam",
                                "activity_type": "one_time", "calendar_date": "2026-10-01"}])
        self.assertEqual(calendar.get_calendar_week(self.connection, date(2026, 10, 5), include_exams=True), [])

    def test_exam_validation_rejects_identity_and_forbidden_fields(self):
        for fields in ({"exam_id": 2, "column_name": "name"},
                       {"exam_id": 1, "column_name": "external_id"}):
            with self.assertRaises(exam_service.ExamValidationError):
                exam_service.validate_exam_edit(1, fields)
