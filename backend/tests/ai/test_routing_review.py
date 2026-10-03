"""Cross-stage exam time-scope policy; no LLM calls."""

import unittest
from datetime import date
from unittest.mock import Mock, patch
from backend.app.ai.context.keywords import choose_agent_context, assess_stage_one
from backend.app.ai.context.intent import context_from_classification
from backend.app.ai.context.contracts import validate_intent_classification
from backend.app.ai.observations import exams
from backend.app.ai.observations.collect import collect_agent_observations


class RoutingReviewTests(unittest.TestCase):
    def test_mixed_history_and_live_exam_questions_keep_fresh_facts(self):
        for message in (
            'Last time we discussed my exam. What is its current date?',
            'What did I just say, and what exams do I have today?',
        ):
            decision = assess_stage_one(message)
            self.assertTrue(decision['confident'])
            self.assertTrue(decision['selection']['include_exams'])
        self.assertIsNotNone(choose_agent_context(
            'Last time we discussed my exam. What is its current date?')['memory'])

    def test_exam_only_scopes_agree(self):
        for scope, phrase in (("today", "today"), ("this_week", "this week"), ("next_week", "next week"), ("month", "this month")):
            with self.subTest(scope=scope):
                expected = context_from_classification({
                    "intent": "exam_query", "time_scope": scope,
                    "include_activities": False, "include_exams": True})
                self.assertEqual(choose_agent_context(f"What exams do I have {phrase}?"), expected)

    def test_study_tonight_still_includes_upcoming_exams(self):
        for message in ("What should I study tonight?", "What should I do today for my exams?"):
            self.assertEqual(choose_agent_context(message), {
                "activities_scope": "today", "include_exams": True, "exam_scope": "upcoming"})

    def test_future_study_windows_keep_upcoming_exams(self):
        for scope, phrase in (("tomorrow", "tomorrow"), ("this_week", "this week"),
                              ("next_week", "next week"), ("month", "this month")):
            with self.subTest(scope=scope):
                expected = {"activities_scope": scope, "include_exams": True, "exam_scope": "upcoming"}
                self.assertEqual(choose_agent_context(f"Help me plan study {phrase} for upcoming exams."), expected)
                # Older callers that omit exam_scope retain a safe planning horizon.
                self.assertEqual(context_from_classification({
                    "intent": "study_planning", "time_scope": scope,
                    "include_activities": True, "include_exams": True,
                }), expected)

    def test_explicit_exam_scope_is_independent_of_intent_and_activity_window(self):
        for intent in ("study_planning", "schedule_query", "exam_query", "activity_query", "general_question"):
            with self.subTest(intent=intent):
                selected = context_from_classification({
                    "intent": intent, "time_scope": "tomorrow", "exam_scope": "today",
                    "include_activities": True, "include_exams": True,
                })
                self.assertEqual(selected, {
                    "activities_scope": "tomorrow", "include_exams": True, "exam_scope": "today",
                })

    def test_today_exam_scope_is_not_inferred_from_intent_label(self):
        for intent in ("exam_query", "general_question", "schedule_query"):
            self.assertEqual(context_from_classification({
                "intent": intent, "time_scope": "today", "include_activities": False,
                "include_exams": True,
            })["exam_scope"], "today")

    def test_different_study_and_exam_windows_reach_semantic_routing(self):
        decision = assess_stage_one("Help me plan study tonight for exams this week.")
        self.assertFalse(decision["confident"])
        selected = context_from_classification({
            "intent": "study_planning", "time_scope": "today", "exam_scope": "this_week",
            "include_activities": True, "include_exams": True,
        })
        self.assertEqual(selected["activities_scope"], "today")
        self.assertEqual(selected["exam_scope"], "this_week")

    def test_exam_scope_rejects_unknown_and_inconsistent_values(self):
        valid = dict(intent="study_planning", time_scope="tomorrow", include_activities=True,
                     include_exams=True, exam_scope="upcoming", confidence="high")
        for changes in ({"exam_scope": "year"}, {"exam_scope": "all"},
                        {"exam_scope": 1}, {"include_exams": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_intent_classification({**valid, **changes})

    def test_tomorrow_study_keeps_exam_later_in_the_week(self):
        selected = context_from_classification({
            "intent": "study_planning", "time_scope": "tomorrow", "exam_scope": "upcoming",
            "include_activities": True, "include_exams": True,
        })
        activities = Mock(return_value={"count": 0})
        with patch.object(exams, "get_current_date", return_value=date(2026, 10, 4)), \
                patch.object(exams, "get_current_time", return_value="09:30"), \
                patch.object(exams, "get_all_exams", return_value=[
                    (1, "Exam next week", "Canvas", "COMPSCI 130", "2026-10-09", "14:00", "16:00"),
                ]):
            context = collect_agent_observations(
                None, selected, activity_builder=activities, exam_builder=exams.build_exam_observation,
            )
        activities.assert_called_once_with(None, scope="tomorrow")
        self.assertEqual(context["exams"]["upcoming"][0]["date"], "2026-10-09")
        self.assertEqual(context["exams"]["upcoming"][0]["days_left"], 5)
