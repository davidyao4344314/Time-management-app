"""Exam-planning regressions: fake model calls and read-only fixture rows."""

import json
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.ai.agent import service, reasoning
from backend.app.ai.agent.coverage import exam_context_coverage, add_exam_coverage_notice
from backend.app.ai.context.exam_policy import choose_exam_filter
from backend.app.ai.context.policy import excluded_context_sources
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.observations import exams
from backend.app.planner.assessment_types import classify_assessment_name


ROWS = [
    (1, "Quiz 9 Functions 2 [MATHS 102]", "Canvas", "MATHS 102", "2026-10-09", None, None),
    (2, "In Class Assignment 3 [PHYSICS 140]", "Canvas", "PHYSICS 140", "2026-10-15", "23:00", "23:00"),
    (3, "Lab20 - Exam Revision [COMPSCI 130]", "Canvas", "COMPSCI 130", "2026-10-24", None, None),
    (4, "PHYSICS 140 Exam", "University", "PHYSICS 140", "2026-11-02", "09:00", "11:15"),
    (5, "ECON 151G Exam", "University", "ECON 151G", "2026-11-06", "09:00", "11:15"),
    (6, "MATHS 102 Exam", "University", "MATHS 102", "2026-11-06", "14:00", "16:30"),
    (7, "COMPSCI 130 Exam", "University", "COMPSCI 130", "2026-11-10", "14:00", "16:30"),
    (8, "Important assessment", "University", "COMPSCI 130", "2026-10-20", None, None),
]
ONLY_EXAMS = "Don't care about like lab and the quiz only the exams"


def turn(user):
    return {"user": user, "assistant": {"message": "Previous advice", "actions": []}}


class ExamSubsetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(exams, "get_current_date", return_value=date(2026, 10, 6)))
        self.stack.enter_context(patch.object(exams, "get_current_time", return_value="08:00"))
        self.stack.enter_context(patch.object(exams, "get_all_exams", return_value=ROWS))

    def test_explicit_labels_not_source_determine_assessment_type(self):
        for name, kind in (
            ("PHYSICS 140 Exam", "exam"), ("Final Examination", "exam"),
            ("Quiz 9 Functions", "quiz"), ("In Class Assignment", "assignment"),
            ("Lab20 - Exam Revision", "preparation"), ("Mock exam", "preparation"),
            ("Midsemester test", "test"), ("Important assessment", "unknown"),
            (None, "unknown"), ("Example topic", "unknown"),
        ):
            with self.subTest(name=name):
                self.assertEqual(classify_assessment_name(name), kind)

    def test_only_exams_never_contains_quizzes_assignments_or_unknowns(self):
        result = exams.build_exam_observation(None, assessment_filter="formal_exams")
        self.assertTrue(result["upcoming"])
        self.assertTrue(all(item["assessment_type"] == "exam" for item in result["upcoming"]))
        self.assertEqual(result["assessment_filter"], "formal_exams")
        self.assertEqual(result["unknown_type_count"], 1)
        self.assertNotIn("In Class Assignment 3 [PHYSICS 140]", [item["name"] for item in result["upcoming"]])

    def test_normal_assessment_observation_keeps_date_only_items_and_labels(self):
        result = exams.build_exam_observation(None)
        quiz = next(item for item in result["upcoming"] if item["assessment_type"] == "quiz")
        self.assertIsNone(quiz["start"])
        self.assertIsNone(quiz["end"])
        self.assertTrue(any(item["assessment_type"] == "assignment" for item in result["upcoming"]))
        with self.assertRaises(ValueError):
            exams.build_exam_observation(None, assessment_filter="made-up")

    def test_current_request_and_bounded_user_history_control_subset(self):
        self.assertEqual(choose_exam_filter(ONLY_EXAMS), "formal_exams")
        self.assertEqual(choose_exam_filter("Make that plan shorter", [turn(ONLY_EXAMS)]), "formal_exams")
        self.assertEqual(choose_exam_filter("Show my quizzes instead", [turn(ONLY_EXAMS)]), "all")
        self.assertEqual(choose_exam_filter("Include assessments too", [turn(ONLY_EXAMS)]), "all")
        self.assertEqual(choose_exam_filter("Don't include quizzes", [turn(ONLY_EXAMS)]), "formal_exams")
        self.assertEqual(choose_exam_filter("Not only exams"), "all")
        self.assertEqual(choose_exam_filter("Show my exams"), "all")
        self.assertEqual(choose_exam_filter("Make that shorter", [turn("Show my quizzes")]), "all")

    def test_quiz_exclusion_does_not_exclude_requested_formal_exams(self):
        self.assertEqual(excluded_context_sources("Ignore quizzes, only the exams"), set())
        self.assertEqual(excluded_context_sources("Don't show my exams, just activities"), {"exams"})
        self.assertEqual(excluded_context_sources("Don't show formal exams"), {"exams"})

    def test_collection_passes_subset_without_changing_activity_selection(self):
        activity, exam = Mock(), Mock()
        collect_agent_observations(None, {"activities_scope": "week", "include_exams": True,
            "exam_scope": "upcoming"}, activity_builder=activity, exam_builder=exam, exam_filter="formal_exams")
        exam.assert_called_once_with(None, scope="upcoming", assessment_filter="formal_exams")
        activity.assert_called_once_with(None, scope="week")


class _AgentFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service, "is_openai_api_key_configured", return_value=True))
        self.stack.enter_context(patch.dict(service.os.environ, {"OPENAI_API_KEY": "offline-test-key"}))
        self.stack.enter_context(patch.object(service, "get_agent_model_settings", return_value={"model": "test-model", "reasoning_effort": "none"}))
        self.stack.enter_context(patch.object(service, "get_max_recent_turns", return_value=5))
        self.stack.enter_context(patch.object(reasoning, "get_max_recent_turns", return_value=5))
        self.router = self.stack.enter_context(patch.object(service, "select_agent_context"))
        self.builder = self.stack.enter_context(patch.object(service, "build_exam_observation", return_value={"count": 1, "upcoming": [{"name": "PHYSICS 140 Exam", "assessment_type": "exam"}]}))
        factory = self.stack.enter_context(patch.object(service, "OpenAI"))
        self.client = factory.return_value.__enter__.return_value

    def respond(self, *proposals):
        self.client.responses.parse.side_effect = [SimpleNamespace(status="completed", output_parsed=value) for value in proposals]


class AgentExamSubsetTests(_AgentFixture):
    def test_initial_exam_context_honors_only_exams_without_extra_model_calls(self):
        self.router.return_value = {"activities_scope": None, "include_exams": True, "exam_scope": "upcoming"}
        self.respond({"message": "Prepare Physics", "actions": []})
        service.get_agent_proposal(None, ONLY_EXAMS)
        self.builder.assert_called_once_with(None, scope="upcoming", assessment_filter="formal_exams")
        self.assertEqual(self.client.responses.parse.call_count, 1)

    def test_recovered_exam_context_keeps_recent_formal_exam_restriction(self):
        self.router.return_value = {"activities_scope": None, "include_exams": False, "exam_scope": None}
        self.respond({"message": None, "actions": [], "missing_context": [{"source": "exams", "time_scope": "upcoming"}]},
                     {"message": "Prepare Physics", "actions": []})
        service.get_agent_proposal(None, "Make the plan shorter", [turn(ONLY_EXAMS)])
        self.builder.assert_called_once_with(None, scope="upcoming", assessment_filter="formal_exams")
        context = json.loads(self.client.responses.parse.call_args_list[1].kwargs["input"][-1]["content"])
        self.assertEqual(context["observations"]["exams"]["upcoming"][0]["assessment_type"], "exam")
        self.assertEqual(self.client.responses.parse.call_count, 2)


class ExamHorizonTests(unittest.TestCase):
    def setUp(self):
        ExamSubsetTests.setUp(self)

    def test_upcoming_contains_all_four_formal_exams_beyond_original_cutoff(self):
        result = exams.build_exam_observation(None, assessment_filter="formal_exams")
        self.assertEqual([item["name"] for item in result["upcoming"]], [
            "PHYSICS 140 Exam", "ECON 151G Exam", "MATHS 102 Exam", "COMPSCI 130 Exam",
        ])
        self.assertEqual(result["count"], 4)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["period"], {"start": "2026-10-06", "end": "2027-01-04"})
        self.assertEqual(result["upcoming"][-1]["days_left"], 35)

    def test_explicit_month_and_week_scopes_do_not_expand_to_ninety_days(self):
        for scope, end in (("month", "2026-10-31"), ("this_week", "2026-10-11")):
            with self.subTest(scope=scope):
                result = exams.build_exam_observation(None, scope=scope, assessment_filter="formal_exams")
                self.assertEqual(result["period"]["end"], end)
                self.assertEqual(result["upcoming"], [])
                self.assertEqual(result["count"], 0)

    def test_horizon_boundaries_past_exams_and_untimed_exams(self):
        rows = [
            (1, "Past Exam", "University", None, "2026-10-05", None, None),
            (2, "Ended Exam", "University", None, "2026-10-06", "06:00", "07:00"),
            (3, "Today's Exam", "University", None, "2026-10-06", None, None),
            (4, "Boundary Exam", "University", None, "2027-01-04", None, None),
            (5, "Beyond Exam", "University", None, "2027-01-05", None, None),
        ]
        with patch.object(exams, "get_all_exams", return_value=rows):
            result = exams.build_exam_observation(None, assessment_filter="formal_exams")
        self.assertEqual([item["name"] for item in result["upcoming"]], ["Today's Exam", "Boundary Exam"])
        self.assertIsNone(result["upcoming"][0]["start"])
        self.assertEqual(result["upcoming"][-1]["days_left"], 90)

    def test_larger_horizon_keeps_detail_limit_and_full_count(self):
        rows = [(index, f"Exam {index}", "University", None,
                 (date(2026, 10, 6) + timedelta(days=index)).isoformat(), None, None)
                for index in range(1, 26)]
        with patch.object(exams, "get_all_exams", return_value=rows):
            result = exams.build_exam_observation(None, assessment_filter="formal_exams")
        self.assertEqual(len(result["upcoming"]), 20)
        self.assertEqual(result["count"], 25)
        self.assertTrue(result["truncated"])


class ExamCoverageTests(unittest.TestCase):
    def observation(self, **overrides):
        return {"period": {"start": "2026-10-06", "end": "2027-01-04"},
                "count": 4, "upcoming": [{"name": row[1]} for row in ROWS[3:7]],
                "assessment_filter": "formal_exams", "unknown_type_count": 0,
                "truncated": False, **overrides}

    def test_complete_detail_still_discloses_bounded_period_and_subset(self):
        coverage = exam_context_coverage(self.observation())
        self.assertIn("6 Oct 2026–4 Jan 2027", coverage["notice"])
        self.assertIn("formal exams identified by explicit names", coverage["notice"])
        self.assertIn("outside this period are not included", coverage["notice"])
        self.assertFalse(coverage["truncated"])
        self.assertEqual(coverage["matching_count"], 4)

    def test_truncated_details_and_unknown_labels_are_explicit(self):
        coverage = exam_context_coverage(self.observation(count=25, upcoming=[{}] * 20,
                                                        truncated=True, unknown_type_count=1))
        self.assertIn("Showing 20 of 25", coverage["notice"])
        self.assertIn("detailed list is incomplete", coverage["notice"])
        self.assertIn("1 ambiguously named assessment was not included", coverage["notice"])

    def test_empty_results_do_not_claim_no_exams_exist_outside_period(self):
        coverage = exam_context_coverage(self.observation(count=0, upcoming=[]))
        self.assertEqual(coverage["matching_count"], 0)
        self.assertIn("outside this period are not included", coverage["notice"])
        self.assertNotIn("no exams", coverage["notice"])

    def test_invalid_or_unavailable_coverage_is_never_invented(self):
        for observation in (None, {"status": "unavailable"}, {}, self.observation(count=-1),
                            self.observation(period={"start": "invalid", "end": "2027-01-04"}),
                            self.observation(period={"start": "2027-01-04", "end": "2026-10-06"})):
            with self.subTest(observation=observation):
                self.assertIsNone(exam_context_coverage(observation))

    def test_notice_is_idempotent_and_preserves_actions(self):
        proposal = {"message": "Here is a study suggestion.", "actions": [{"tool": "add_activity"}],
                    "memory_request": None, "missing_context": []}
        coverage = exam_context_coverage(self.observation())
        result = add_exam_coverage_notice(proposal, coverage)
        self.assertEqual(result["actions"], proposal["actions"])
        self.assertEqual(result, add_exam_coverage_notice(result, coverage))
        self.assertEqual(proposal["message"], "Here is a study suggestion.")
        self.assertEqual(add_exam_coverage_notice(proposal, None), proposal)

    def test_model_input_separates_current_coverage_from_older_chat(self):
        observed = self.observation()
        messages = reasoning.build_agent_messages("Only the exams", {"exams": observed},
                                                   [turn("There are no upcoming exams")])
        payload = json.loads(messages[-1]["content"])
        self.assertEqual(payload["observation_coverage"]["exams"]["matching_count"], 4)
        self.assertEqual(payload["observations"]["exams"], observed)
        self.assertIn("not the source of truth", reasoning.STUDY_PLANNING_INSTRUCTIONS)
        self.assertIn("never say it is the user's complete exam timetable", reasoning.STUDY_PLANNING_INSTRUCTIONS)


class AgentCoverageTests(_AgentFixture):
    def test_reply_and_inspector_use_the_same_backend_coverage_without_extra_call(self):
        self.router.return_value = {"activities_scope": None, "include_exams": True, "exam_scope": "upcoming"}
        self.builder.return_value = ExamCoverageTests().observation()
        self.respond({"message": "Prepare for your four formal exams.", "actions": []})
        result = service.get_agent_proposal(None, ONLY_EXAMS, include_context=True)
        coverage = result["agent_context"]["exam_coverage"]
        self.assertIn(coverage["notice"], result["message"])
        source = next(source for source in result["agent_context"]["context_sources"] if source["source"] == "exams")
        self.assertIn(coverage["notice"], source["reason"])
        self.assertEqual(self.client.responses.parse.call_count, 1)

    def test_recovered_exam_period_is_not_reported_before_it_is_observed(self):
        self.router.return_value = {"activities_scope": None, "include_exams": False, "exam_scope": None}
        self.builder.return_value = ExamCoverageTests().observation()
        self.respond({"message": None, "actions": [], "missing_context": [{"source": "exams", "time_scope": "upcoming"}]},
                     {"message": "Prepare for your exams.", "actions": []})
        result = service.get_agent_proposal(None, ONLY_EXAMS, include_context=True)
        first = json.loads(self.client.responses.parse.call_args_list[0].kwargs["input"][-1]["content"])
        second = json.loads(self.client.responses.parse.call_args_list[1].kwargs["input"][-1]["content"])
        self.assertNotIn("observation_coverage", first)
        self.assertEqual(second["observation_coverage"]["exams"], result["agent_context"]["exam_coverage"])
        self.assertIn("6 Oct 2026–4 Jan 2027", result["message"])


if __name__ == "__main__":
    unittest.main()
