"""Explicit exclusions survive routing, observation collection and recovery."""

import unittest
from unittest.mock import Mock, patch

from backend.app.ai.context.contracts import AgentIntentClassification, AgentRoutingDecision
from backend.app.ai.context.keywords import assess_stage_one, choose_agent_context
from backend.app.ai.context.policy import apply_context_exclusions, excluded_context_sources
from backend.app.ai.context import selection as routing
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.agent.context_recovery import recovery_selection


SELECTED = {"activities_scope": "tomorrow", "include_exams": True, "exam_scope": "tomorrow"}
EXCLUDED = {"activities_scope": None, "include_exams": False, "exam_scope": None}


class ContextPolicyTests(unittest.TestCase):
    def test_explicit_calendar_exclusion_blocks_both_calendar_sources(self):
        for message in (
            "Don't use my calendar; give general wake-up advice for tomorrow.",
            "DO NOT CONSULT MY SCHEDULE tomorrow.",
            "Give advice without my timetable.",
            "Give generic advice without using my calendar.",
            "Give generic advice without considering my schedule.",
        ):
            with self.subTest(message=message):
                self.assertEqual(excluded_context_sources(message), {"activities", "exams"})
                self.assertEqual(choose_agent_context(message), EXCLUDED)
                self.assertFalse(assess_stage_one(message)["confident"])

    def test_exam_exclusion_preserves_requested_activities(self):
        message = "Don’t show me exams, just tell me my schedule tomorrow."
        self.assertEqual(excluded_context_sources(message), {"exams"})
        self.assertEqual(choose_agent_context(message), {
            "activities_scope": "tomorrow", "include_exams": False, "exam_scope": None,
        })

    def test_exclusion_does_not_extend_into_a_separate_positive_request(self):
        for message in (
            "Don't show exams and tell me my activities tomorrow.",
            "Don't include exams. Show my activities tomorrow.",
            "Ignore exams, but use my activities tomorrow.",
        ):
            self.assertEqual(excluded_context_sources(message), {"exams"})

    def test_multiple_direct_source_objects_can_be_excluded(self):
        self.assertEqual(excluded_context_sources("Don't show me activities or exams."),
                         {"activities", "exams"})
        self.assertEqual(excluded_context_sources("Ignore my activities and upcoming exams."),
                         {"activities", "exams"})

    def test_arbitrary_negation_does_not_exclude_observations(self):
        for message in (
            "I'm not sure what my exams are.",
            "Don't delete my activities.",
            "Please show my calendar tomorrow.",
        ):
            self.assertEqual(excluded_context_sources(message), set())

    def test_exclusion_must_apply_to_the_source_not_an_unrelated_verb(self):
        for message in (
            "Help me plan study without forgetting my exams tomorrow.",
            "Don't ignore my activities tomorrow.",
            "Never skip my exams tomorrow.",
        ):
            with self.subTest(message=message):
                self.assertEqual(excluded_context_sources(message), set())

    def test_policy_does_not_mutate_selection_or_memory(self):
        original = {**SELECTED, "memory": {"scope": "current_chat"}}
        self.assertEqual(apply_context_exclusions(original, {"activities", "exams"}), {
            **EXCLUDED, "memory": original["memory"],
        })
        self.assertEqual(original, {**SELECTED, "memory": {"scope": "current_chat"}})

    def test_all_routing_paths_enforce_exclusions_even_when_models_are_wrong(self):
        decision = dict(intent="general_question", time_scope="tomorrow",
                        include_activities=True, include_exams=True)
        message = "Don't use my calendar; give generic advice for tomorrow."
        for stage in ("stage_1", "stage_2", "stage_3", "safe_fallback"):
            with self.subTest(stage=stage), \
                    patch.object(routing, "assess_stage_one", return_value={
                        "selection": SELECTED, "confident": stage == "stage_1", "reason": "test",
                    }), \
                    patch.object(routing, "classify_agent_intent") as stage_two, \
                    patch.object(routing, "classify_stage_three") as stage_three:
                stage_two.return_value = AgentIntentClassification(**decision, confidence="high")
                stage_three.return_value = AgentRoutingDecision(**decision)
                if stage in ("stage_3", "safe_fallback"):
                    stage_two.side_effect = ValueError("Invalid classification")
                if stage == "safe_fallback":
                    stage_three.side_effect = ValueError("No classification")
                trace = {}
                selected = routing.select_agent_context(Mock(), message, [], "test-model", trace=trace)
                self.assertEqual(selected, EXCLUDED)
                self.assertEqual(trace["stage"], stage)

    def test_collection_never_calls_excluded_builders(self):
        activities, exams = Mock(), Mock()
        result = collect_agent_observations(
            None, SELECTED, activity_builder=activities, exam_builder=exams,
            excluded_sources={"activities", "exams"},
        )
        self.assertEqual(result, {})
        activities.assert_not_called()
        exams.assert_not_called()

    def test_recovery_rejects_excluded_but_unselected_source(self):
        with self.assertRaisesRegex(ValueError, "excluded"):
            recovery_selection(
                [{"source": "activities", "time_scope": "tomorrow"}],
                {"activities": "not_selected"}, excluded_sources={"activities"},
            )

    def test_non_personal_time_mentions_reach_semantic_routing(self):
        for message in ("Tell me a joke about alarm clocks tomorrow.",
                        "How does an alarm clock work today?"):
            self.assertFalse(assess_stage_one(message)["confident"])


if __name__ == "__main__":
    unittest.main()
