"""Observation selection stays read-only and independent from reasoning."""

import unittest
from unittest.mock import Mock

from backend.app.observations.collect import collect_agent_observations


class ObservationCollectionTests(unittest.TestCase):
    def test_builds_only_selected_sections_and_preserves_scope(self):
        activity = Mock(return_value={"today": []})
        exam = Mock(return_value={"upcoming": []})
        connection = object()
        result = collect_agent_observations(
            connection,
            {"activities_scope": None, "include_exams": True, "exam_scope": "month"},
            activity_builder=activity, exam_builder=exam,
        )
        self.assertEqual(result, {"exams": {"upcoming": []}})
        activity.assert_not_called()
        exam.assert_called_once_with(connection, scope="month")

    def test_multiple_intents_keep_observations_separate(self):
        activity = Mock(return_value={"today": []})
        exam = Mock(return_value={"upcoming": []})
        result = collect_agent_observations(
            None,
            {"activities_scope": "today", "include_exams": True, "exam_scope": "upcoming"},
            activity_builder=activity, exam_builder=exam,
        )
        self.assertEqual(set(result), {"activities", "exams"})
        activity.assert_called_once_with(None, scope="today")
        exam.assert_called_once_with(None, scope="upcoming")


if __name__ == "__main__":
    unittest.main()
