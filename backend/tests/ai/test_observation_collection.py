"""Observation selection stays read-only and independent from reasoning."""

import unittest
from unittest.mock import Mock

from backend.app.ai.context.intent import context_from_classification
from backend.app.ai.observations.collect import collect_agent_observations


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

    def test_general_question_loads_tomorrow_when_schedule_is_required(self):
        activity = Mock(return_value={"upcoming_7d": [{"name": "Lecture"}]})
        exam = Mock()
        memory = Mock()
        connection = object()
        selection = context_from_classification({
            "intent": "general_question", "time_scope": "tomorrow",
            "include_activities": True, "include_exams": False,
        })
        result = collect_agent_observations(
            connection, selection, activity_builder=activity,
            exam_builder=exam, memory_builder=memory,
        )
        self.assertEqual(result, {"activities": activity.return_value})
        activity.assert_called_once_with(connection, scope="tomorrow")
        exam.assert_not_called()
        memory.assert_not_called()

    def test_generic_question_does_not_load_unrequested_observations(self):
        activity = Mock()
        exam = Mock()
        memory = Mock()
        selection = context_from_classification({
            "intent": "general_question", "time_scope": "unspecified",
            "include_activities": False, "include_exams": False,
        })
        result = collect_agent_observations(
            None, selection, activity_builder=activity,
            exam_builder=exam, memory_builder=memory,
        )
        self.assertEqual(result, {})
        activity.assert_not_called()
        exam.assert_not_called()
        memory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
