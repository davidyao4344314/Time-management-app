"""Activity service and HTTP equivalence checks using disposable databases only."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import call, patch

from fastapi.testclient import TestClient

from backend import fastapi_test as api
from backend.app import activity_service as service, activities, database


def activity_fields(**changes):
    fields = {
        "name": " Study ", "category": " Learning ", "subject": "COMPSCI 130",
        "activity_type": "one_time", "date": "2026-10-01", "weekday": None,
        "start_time": "09:00", "end_time": "10:00",
    }
    fields.update(changes)
    return fields


class ActivityServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(database.sql_file.read_text())

    def test_create_types_keep_unused_fields_null_and_optional_times(self):
        for activity_type in ("one_time", "daily", "weekly"):
            with self.subTest(activity_type=activity_type):
                prepared = service.prepare_new_activity(activity_fields(
                    activity_type=activity_type, weekday="monday",
                    start_time=None, end_time=None,
                ))
                row = service.create_activity_record(self.connection, prepared)
                self.assertEqual(row[1:3], ("Study", "Learning"))
                self.assertEqual(row[4], activity_type)
                self.assertEqual(row[5], "2026-10-01" if activity_type == "one_time" else None)
                self.assertEqual(row[6], "Monday" if activity_type == "weekly" else None)
                self.assertEqual(row[7:9], (None, None))
                self.assertEqual(row[11:13], ("Manual", None))

    def test_edit_keeps_import_metadata_mapping_and_identity(self):
        columns, values = service.prepare_new_activity(activity_fields(
            activity_type="weekly", weekday="Monday",
        ))
        activity_id = activities.add_activity(
            self.connection, columns + ["source", "active_start_date", "active_end_date"],
            values + ["UoA", "2026-07-20", "2026-11-01"],
        )
        activities.save_uoa_external_ids(self.connection, activity_id, ["fake-uid-1", "fake-uid-2"])
        before = activities.get_activity_by_id(self.connection, activity_id)
        after = service.update_activity_record(self.connection, activity_id, {
            "activity_id": activity_id, "column_name": "name", "new_value": "New lecture name",
        })
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], "New lecture name")
        self.assertEqual(after[2:], before[2:])
        mappings = self.connection.execute(
            "SELECT external_id FROM uoa_activity_external_ids WHERE activity_id=? ORDER BY external_id",
            (activity_id,),
        ).fetchall()
        self.assertEqual(mappings, [("fake-uid-1",), ("fake-uid-2",)])

    def test_recurrence_edits_keep_existing_per_field_call_order(self):
        row = service.create_activity_record(self.connection, service.prepare_new_activity(activity_fields()))
        with patch.object(service, "edit_activity", wraps=activities.edit_activity) as edit:
            updated = service.update_activity_record(self.connection, row[0], {
                "activity_id": row[0], "column_name": "activity_type",
                "new_value": "weekly", "weekday": "wednesday",
            })
        self.assertEqual(edit.call_args_list, [
            call(self.connection, row[0], "activity_type", "weekly", commit=False),
            call(self.connection, row[0], "weekday", "Wednesday", commit=False),
            call(self.connection, row[0], "date", None, commit=False),
        ])
        self.assertEqual(updated[4:7], ("weekly", None, "Wednesday"))
        updated = service.update_activity_record(self.connection, row[0], {
            "activity_id": row[0], "column_name": "activity_type", "new_value": "daily",
        })
        self.assertEqual(updated[4:7], ("daily", None, None))

    def test_invalid_values_or_metadata_columns_do_not_write(self):
        row = service.create_activity_record(self.connection, service.prepare_new_activity(activity_fields()))
        invalid = [
            {"column_name": "source", "new_value": "Canvas"},
            {"column_name": "external_id", "new_value": "fake-uid"},
            {"column_name": "id", "new_value": "99"},
            {"column_name": "weekday", "new_value": "Monday"},
            {"column_name": "end_time", "new_value": "08:00"},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(service.ActivityValidationError):
                service.update_activity_record(self.connection, row[0], {"activity_id": row[0], **fields})
            self.assertEqual(activities.get_activity_by_id(self.connection, row[0]), row)

    def test_invalid_create_values_keep_original_errors(self):
        cases = [
            ({"name": " "}, "Name and category are required."),
            ({"activity_type": "monthly"}, "Invalid activity type."),
            ({"date": None}, "A date is required for a one-time activity."),
            ({"start_time": "not-a-time"}, "Times must use HH:MM format."),
            ({"end_time": "08:00"}, "End time must be later than start time."),
        ]
        for changes, detail in cases:
            with self.subTest(changes=changes), self.assertRaises(service.ActivityValidationError) as caught:
                service.prepare_new_activity(activity_fields(**changes))
            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(caught.exception.detail, detail)


class ActivityServiceHTTPTests(unittest.TestCase):
    def test_invalid_identity_and_column_are_checked_before_connection(self):
        client = TestClient(api.app)
        with patch.object(api, "create_connection") as connect:
            mismatch = client.put("/activities/1", json={
                "activity_id": 2, "column_name": "name", "new_value": "New name",
            })
            forbidden = client.put("/activities/1", json={
                "activity_id": 1, "column_name": "external_id", "new_value": "fake-uid",
            })
        connect.assert_not_called()
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(forbidden.json(), {"detail": "That field cannot be edited."})

    def test_add_edit_and_exam_validation_keep_existing_http_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(database.sql_file.read_text())
            with patch.object(api, "create_connection", side_effect=lambda: sqlite3.connect(path)):
                client = TestClient(api.app)
                created = client.post("/activities", json=activity_fields())
                self.assertEqual(created.status_code, 201)
                activity_id = created.json()["id"]
                updated = client.put(f"/activities/{activity_id}", json={
                    "activity_id": activity_id, "column_name": "subject", "new_value": "MATHS",
                })
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["id"], activity_id)
                self.assertEqual(updated.json()["source"], "Manual")
                self.assertIsNone(updated.json()["external_id"])
                self.assertEqual(updated.json()["subject"], "MATHS")
                exam = client.post("/exams", json={
                    "name": "Test", "category": "Assessment", "date": "2026-10-01",
                    "start_time": "11:00", "end_time": "10:00",
                })
                self.assertEqual(exam.status_code, 400)
                self.assertEqual(exam.json(), {"detail": "End time must be later than start time."})


if __name__ == "__main__":
    unittest.main()
