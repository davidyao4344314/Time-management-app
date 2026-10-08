"""Offline conflict checks against the real schema in disposable SQLite only.

Run from the project root:
backend/.venv/bin/python -B -m unittest backend.tests.planner.test_activity_conflicts -v
"""

import json
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch

from backend.app import database
from backend.app.planner import calendar
from backend.app.planner.activities import add_activity, get_all_activities
from backend.app.planner.conflicts import find_activity_conflicts


def activity(**changes):
    fields = {
        "name": "Study", "category": "Study", "subject": "COMPSCI 130",
        "activity_type": "one_time", "date": "2026-10-12", "weekday": None,
        "start_time": "09:00", "end_time": "10:00",
    }
    fields.update(changes)
    return fields


class ActivityConflictTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(database.sql_file.read_text())
        clock = patch.object(calendar, "get_current_date", return_value=date(2026, 10, 9))
        clock.start()
        self.addCleanup(clock.stop)

    def add(self, **changes):
        fields = activity(**changes)
        return add_activity(self.connection, list(fields), list(fields.values()))

    def check(self, exclude_activity_id=None, **changes):
        return find_activity_conflicts(self.connection, activity(**changes), exclude_activity_id)

    def test_partial_overlap_returns_existing_identity_and_resolved_date(self):
        activity_id = self.add(name="Physics")
        self.assertEqual(self.check(start_time="09:30", end_time="10:30"), [{
            "activity_id": activity_id, "name": "Physics", "date": "2026-10-12",
            "start_time": "09:00", "end_time": "10:00",
        }])

    def test_touching_ranges_in_either_direction_are_allowed(self):
        self.add()
        self.assertEqual(self.check(start_time="10:00", end_time="11:00"), [])
        self.assertEqual(self.check(start_time="08:00", end_time="09:00"), [])

    def test_equal_and_containing_ranges_conflict(self):
        self.add()
        for start, end in [("09:00", "10:00"), ("08:00", "11:00"), ("09:15", "09:45")]:
            with self.subTest(start=start, end=end):
                self.assertEqual(len(self.check(start_time=start, end_time=end)), 1)

    def test_same_times_on_different_dates_do_not_conflict(self):
        self.add(date="2026-10-13")
        self.assertEqual(self.check(), [])

    def test_existing_weekly_activity_matches_only_its_weekday(self):
        self.add(activity_type="weekly", date=None, weekday="Monday")
        self.assertEqual(len(self.check()), 1)
        self.assertEqual(self.check(date="2026-10-13"), [])

    def test_weekly_candidate_matches_existing_one_time_date(self):
        self.add()
        self.assertEqual(len(self.check(activity_type="weekly", date=None, weekday="Monday")), 1)
        self.assertEqual(self.check(activity_type="weekly", date=None, weekday="Tuesday"), [])

    def test_weekly_pairs_resolve_a_date_not_just_equal_times(self):
        self.add(activity_type="weekly", date=None, weekday="Monday")
        result = self.check(activity_type="weekly", date=None, weekday="Monday")
        self.assertEqual(result[0]["date"], "2026-10-12")
        self.assertEqual(self.check(activity_type="weekly", date=None, weekday="Tuesday"), [])

    def test_daily_candidate_finds_future_one_time_beyond_current_week(self):
        self.add(date="2027-01-18")
        result = self.check(activity_type="daily", date=None)
        self.assertEqual(result[0]["date"], "2027-01-18")

    def test_daily_and_weekly_recurrences_return_one_date_per_row(self):
        self.add(activity_type="weekly", date=None, weekday="Thursday")
        daily_id = self.add(activity_type="daily", date=None)
        result = self.check(activity_type="daily", date=None)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["activity_id"], daily_id)
        self.assertEqual([item["date"] for item in result], ["2026-10-09", "2026-10-15"])

    def test_update_excludes_self_but_keeps_other_conflicts(self):
        own_id = self.add()
        other_id = self.add(name="Other")
        self.assertEqual([item["activity_id"] for item in self.check(own_id)], [other_id])
        self.assertEqual(len(self.check()), 2)

    def test_nullable_missing_malformed_equal_and_reversed_times_are_ignored(self):
        cases = [(None, None), (None, "10:00"), ("09:00", None), ("", "10:00"),
                 ("bad", "10:00"), ("09:00", "24:00"), ("10:00", "10:00"), ("11:00", "10:00")]
        for start, end in cases:
            self.add(start_time=start, end_time=end)
        self.assertEqual(self.check(), [])
        self.add()
        for start, end in cases:
            with self.subTest(start=start, end=end):
                self.assertEqual(self.check(start_time=start, end_time=end), [])

    def test_non_padded_and_whitespace_times_are_compared_as_times(self):
        self.add(start_time=" 9:00 ", end_time=" 10:00 ")
        result = self.check(start_time="9:30", end_time="10:30")
        self.assertEqual(result[0]["start_time"], "09:00")

    def test_active_range_boundaries_are_inclusive(self):
        self.add(activity_type="weekly", date=None, weekday="Monday", source="UoA",
                 active_start_date="2026-10-12", active_end_date="2026-10-19")
        for day in ["2026-10-12", "2026-10-19"]:
            with self.subTest(day=day):
                self.assertEqual(len(self.check(date=day)), 1)
        for day in ["2026-10-05", "2026-10-26"]:
            with self.subTest(day=day):
                self.assertEqual(self.check(date=day), [])

    def test_recurring_pairs_use_shared_range_even_in_a_future_semester(self):
        self.add(activity_type="weekly", date=None, weekday="Monday",
                 active_start_date="2027-03-01", active_end_date="2027-06-01")
        result = self.check(activity_type="weekly", date=None, weekday="Monday",
                            active_start_date="2027-04-06", active_end_date="2027-07-01")
        self.assertEqual(result[0]["date"], "2027-04-12")
        self.assertEqual(self.check(activity_type="weekly", date=None, weekday="Monday",
                                   active_start_date="2027-07-01", active_end_date="2027-08-01"), [])

    def test_short_active_window_without_matching_weekday_has_no_occurrence(self):
        self.add(activity_type="daily", date=None)
        self.assertEqual(self.check(activity_type="weekly", date=None, weekday="Monday",
                                   active_start_date="2026-10-13", active_end_date="2026-10-15"), [])

    def test_invalid_dates_weekdays_and_ranges_are_safely_ignored(self):
        invalid = [
            {"date": None}, {"date": "bad"}, {"date": "2026-02-30"},
            {"activity_type": "weekly", "date": None, "weekday": None},
            {"activity_type": "weekly", "date": None, "weekday": "Funday"},
            {"activity_type": "weekly", "weekday": "Monday", "active_start_date": "bad", "active_end_date": "2026-11-01"},
            {"activity_type": "weekly", "weekday": "Monday", "active_start_date": None, "active_end_date": "2026-11-01"},
            {"activity_type": "weekly", "weekday": "Monday", "active_start_date": "2026-11-01", "active_end_date": None},
            {"activity_type": "weekly", "weekday": "Monday", "active_start_date": "2026-11-01", "active_end_date": "2026-10-01"},
        ]
        for fields in invalid:
            self.add(**fields)
        self.assertEqual(self.check(), [])
        self.add()
        for fields in invalid + [{"activity_type": "monthly"}, {"activity_type": None}]:
            with self.subTest(fields=fields):
                self.assertEqual(self.check(**fields), [])

    def test_date_extremes_do_not_overflow(self):
        self.add(activity_type="daily", date=None)
        result = self.check(activity_type="weekly", date=None, weekday="Friday",
                            active_start_date="9999-12-31", active_end_date="9999-12-31")
        self.assertEqual(result[0]["date"], "9999-12-31")
        self.assertEqual(len(self.check(date="0001-01-01")), 1)

    def test_calendar_predicate_and_time_validator_are_reused(self):
        self.add()
        with patch.object(calendar, "is_activity_on_date", wraps=calendar.is_activity_on_date) as occurs, \
                patch.object(calendar, "is_valid_activity_time", wraps=calendar.is_valid_activity_time) as timed:
            self.assertEqual(len(self.check()), 1)
        self.assertEqual(occurs.call_count, 2)
        self.assertEqual(timed.call_count, 2)
        with patch.object(calendar, "is_activity_on_date", return_value=False):
            self.assertEqual(self.check(), [])

    def test_detection_is_read_only_preserves_transaction_and_excludes_exams(self):
        self.add()
        self.connection.execute(
            "INSERT INTO exams (name, category, date, start_time, end_time) VALUES (?, ?, ?, ?, ?)",
            ("Exam", "Assessment", "2026-10-12", "09:00", "10:00"),
        )
        before = get_all_activities(self.connection)
        before_changes = self.connection.total_changes
        self.connection.execute("PRAGMA query_only = ON")
        candidate = activity()
        original = candidate.copy()
        result = find_activity_conflicts(self.connection, candidate)
        self.assertEqual(len(result), 1)
        self.assertEqual(get_all_activities(self.connection), before)
        self.assertEqual(self.connection.total_changes, before_changes)
        self.assertTrue(self.connection.in_transaction)
        self.assertEqual(candidate, original)
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.connection.rollback()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM exams").fetchone()[0], 0)

    def test_empty_database_has_no_conflicts(self):
        self.assertEqual(self.check(), [])


if __name__ == "__main__":
    unittest.main()
