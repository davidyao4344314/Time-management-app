"""Future observations contain only their requested dates, without today data."""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend.app.ai.observations import activities
from backend.app.ai.observations.formatting import observation_date_range
from backend.app.ai.agent.context_recovery import build_context_status


TODAY = date(2026, 10, 4)
CURRENT = (1, "TODAY CURRENT", "Study", "PHYSICS", "one_time", "2026-10-04", None, "09:00", "10:00")
NEXT = (2, "TODAY NEXT", "Study", "MATHS", "one_time", "2026-10-04", None, "14:00", "15:00")


def occurrence(identifier, name, day, start="11:00", end="12:00"):
    return {"id": identifier, "name": name, "calendar_date": day.isoformat(),
            "start_time": start, "end_time": end}


class ActivityObservationScopeTests(unittest.TestCase):
    def test_future_windows_never_query_or_include_todays_current_and_next(self):
        for scope in ("tomorrow", "next_week"):
            with self.subTest(scope=scope), \
                    patch.object(activities, "get_current_date", return_value=TODAY), \
                    patch.object(activities, "get_current_time") as clock, \
                    patch.object(activities, "get_current_and_next_activities", return_value=([CURRENT], NEXT)) as current, \
                    patch.object(activities, "get_week_activities", return_value=[
                        occurrence(1, "TODAY CURRENT", TODAY, "09:00", "10:00"),
                        occurrence(3, "TOMORROW CLASS", TODAY + timedelta(days=1)),
                    ]):
                result = activities.build_activity_observation(None, scope=scope)
                current.assert_not_called()
                clock.assert_not_called()
                for field in ("current", "current_count", "next", "today", "today_count"):
                    self.assertNotIn(field, result)
                first, last = observation_date_range(TODAY, scope)
                self.assertEqual(result["period"], {"start": first.isoformat(), "end": last.isoformat()})
                self.assertEqual([item["name"] for item in result["upcoming_7d"]], ["TOMORROW CLASS"])
                self.assertEqual(result["count"], 1)

    def test_windows_containing_today_preserve_current_next_and_remaining_items(self):
        rows = [occurrence(1, "TODAY CURRENT", TODAY, "09:00", "10:00"),
                occurrence(2, "TODAY NEXT", TODAY, "14:00", "15:00"),
                occurrence(3, "ALREADY ENDED", TODAY, "08:00", "09:00")]

        def calendar_rows(connection, start):
            return [row for row in rows if start.isoformat() <= row["calendar_date"]
                    <= (start + timedelta(days=6)).isoformat()]

        for scope in ("today", "week", "this_week", "month"):
            with self.subTest(scope=scope), \
                    patch.object(activities, "get_current_date", return_value=TODAY), \
                    patch.object(activities, "get_current_time", return_value="09:30"), \
                    patch.object(activities, "get_current_and_next_activities", return_value=([CURRENT], NEXT)) as current, \
                    patch.object(activities, "get_week_activities", side_effect=calendar_rows):
                result = activities.build_activity_observation(None, scope=scope)
                current.assert_called_once_with(None)
                self.assertEqual(result["current"][0]["name"], "TODAY CURRENT")
                self.assertEqual(result["next"]["name"], "TODAY NEXT")
                self.assertEqual([item["name"] for item in result["today"]], ["TODAY CURRENT", "TODAY NEXT"])
                self.assertEqual(result["count"], 2)

    def test_future_date_only_activity_keeps_null_times(self):
        with patch.object(activities, "get_current_date", return_value=TODAY), \
                patch.object(activities, "get_current_and_next_activities") as current, \
                patch.object(activities, "get_week_activities", return_value=[
                    occurrence(3, "Assignment", TODAY + timedelta(days=1), None, None),
                ]):
            result = activities.build_activity_observation(None, scope="tomorrow")
        current.assert_not_called()
        self.assertEqual(result["upcoming_7d"], [{
            "name": "Assignment", "date": "2026-10-05", "start": None, "end": None,
        }])
        self.assertEqual(result["untimed_count"], 1)
        self.assertEqual(result["busy"], {})

    def test_empty_future_window_does_not_claim_today_is_provided(self):
        with patch.object(activities, "get_current_date", return_value=TODAY), \
                patch.object(activities, "get_current_and_next_activities", return_value=([CURRENT], NEXT)) as current, \
                patch.object(activities, "get_week_activities", return_value=[]):
            result = activities.build_activity_observation(None, scope="next_week")
        current.assert_not_called()
        self.assertEqual(result["count"], 0)
        self.assertEqual(build_context_status({"activities": result})["activities"], "empty")


if __name__ == "__main__":
    unittest.main()
