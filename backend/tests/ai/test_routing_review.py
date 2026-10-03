"""Cross-stage exam time-scope policy; no LLM calls."""

import unittest
from backend.app.ai.context.keywords import choose_agent_context, assess_stage_one
from backend.app.ai.context.intent import context_from_classification


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
