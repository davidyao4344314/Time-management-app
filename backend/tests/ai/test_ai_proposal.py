"""Proposal validation and API tests; never contact OpenAI or change SQLite."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from fastapi.testclient import TestClient

from backend import fastapi_test as api
from backend.app import (
    activity_observation, ai_config, ai_context_router, ai_intent_classifier, ai_memory, ai_proposal,
    ai_routing_pipeline, ai_stage_three_router, exam_observation,
)


def activity_action(**changes):
    arguments = {
        "name": "COMPSCI revision",
        "category": "Study",
        "subject": "COMPSCI 130",
        "activity_type": "one_time",
        "date": "2026-09-26",
        "weekday": None,
        "start_time": "18:00",
        "end_time": "19:00",
    }
    arguments.update(changes)
    return {"tool": "add_activity", "arguments": arguments}


class AIProposalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        archive_patch = patch.object(ai_memory, "ARCHIVE_FILE", Path(directory.name) / "archive.jsonl")
        archive_patch.start()
        self.addCleanup(archive_patch.stop)
        # Existing tests describe the default five-turn behavior regardless of
        # the developer's local, ignored .env setting.
        for target in (ai_memory, ai_proposal):
            limit_patch = patch.object(target, "get_max_recent_turns", return_value=5)
            limit_patch.start()
            self.addCleanup(limit_patch.stop)

    def test_recent_turn_limit_is_saved_and_validated(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_config, "AI_ENV_FILE", Path(directory) / ".env"), \
                patch.dict(ai_config.os.environ, {ai_config.RECENT_TURNS_ENV_KEY: "5"}):
            self.assertEqual(ai_config.get_max_recent_turns(), 5)
            for value in (4, 101, 5.5, True, "20"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    ai_config.save_max_recent_turns(value)

            self.assertEqual(ai_config.save_max_recent_turns(100), {"max_recent_turns": 100})
            self.assertEqual(ai_config.get_max_recent_turns(), 100)
            self.assertIn("OPENAI_AGENT_MAX_RECENT_TURNS", ai_config.AI_ENV_FILE.read_text())
            self.assertEqual(ai_config.AI_ENV_FILE.stat().st_mode & 0o777, 0o600)

    def test_recent_turn_limit_api(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_config, "AI_ENV_FILE", Path(directory) / ".env"), \
                patch.dict(ai_config.os.environ, {ai_config.RECENT_TURNS_ENV_KEY: "5"}):
            client = TestClient(api.app)
            initial = client.get("/ai/memory-config")
            invalid_low = client.put("/ai/memory-config", json={"max_recent_turns": 4})
            invalid_high = client.put("/ai/memory-config", json={"max_recent_turns": 101})
            invalid_type = client.put("/ai/memory-config", json={"max_recent_turns": "20"})
            saved = client.put("/ai/memory-config", json={"max_recent_turns": 20})
            updated = client.get("/ai/memory-config")

        self.assertEqual(initial.json(), {"max_recent_turns": 5, "min": 5, "max": 100})
        self.assertEqual(invalid_low.status_code, 400)
        self.assertEqual(invalid_high.status_code, 400)
        self.assertEqual(invalid_type.status_code, 422)
        self.assertEqual(saved.json(), {"max_recent_turns": 20})
        self.assertEqual(updated.json()["max_recent_turns"], 20)

    def test_model_settings_allow_only_supported_openai_pairs(self):
        self.assertIn("gpt-6-luna", ai_config.AGENT_MODEL_OPTIONS)
        self.assertNotIn("none", ai_config.AGENT_MODEL_OPTIONS["gpt-6-astra"])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_config, "AI_ENV_FILE", Path(directory) / ".env"), \
                patch.dict(ai_config.os.environ, {
                    "OPENAI_AGENT_MODEL": "gpt-6-luna",
                    "OPENAI_AGENT_REASONING_EFFORT": "none",
                }):
            with self.assertRaisesRegex(ValueError, "supported OpenAI model"):
                ai_config.save_agent_model_settings("not-an-openai-model", "low")
            with self.assertRaisesRegex(ValueError, "supported by that model"):
                ai_config.save_agent_model_settings("gpt-6-astra", "none")
            self.assertFalse(ai_config.AI_ENV_FILE.exists())

            saved = ai_config.save_agent_model_settings("gpt-6.1-sol", "high")
            self.assertEqual(saved, {"model": "gpt-6.1-sol", "reasoning_effort": "high"})
            self.assertEqual(ai_config.get_agent_model_settings(), saved)
            self.assertIn("OPENAI_AGENT_MODEL", ai_config.AI_ENV_FILE.read_text())
            self.assertEqual(ai_config.AI_ENV_FILE.stat().st_mode & 0o777, 0o600)

    def test_model_settings_api_returns_choices_and_rejects_invalid_pair(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_config, "AI_ENV_FILE", Path(directory) / ".env"), \
                patch.dict(ai_config.os.environ, {
                    "OPENAI_AGENT_MODEL": "gpt-6-luna",
                    "OPENAI_AGENT_REASONING_EFFORT": "none",
                }):
            client = TestClient(api.app)
            status = client.get("/ai/model-config")
            invalid = client.put("/ai/model-config", json={
                "model": "gpt-6-astra", "reasoning_effort": "none",
            })
            valid = client.put("/ai/model-config", json={
                "model": "gpt-6-sol", "reasoning_effort": "xhigh",
            })
            updated = client.get("/ai/model-config")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["model"], "gpt-6-luna")
        self.assertIn("gpt-6-sol", [choice["id"] for choice in status.json()["models"]])
        self.assertNotIn("api_key", status.json())
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(updated.json()["model"], "gpt-6-sol")
        self.assertEqual(updated.json()["reasoning_effort"], "xhigh")

    def test_stage_two_classification_examples(self):
        cases = (
            ("What should I study tonight?", "study_planning", "today", True, True,
             "today", "upcoming"),
            ("What exams do I have this month?", "exam_query", "month", False, True,
             None, "month"),
            ("What am I doing this week?", "schedule_query", "week", True, False,
             "week", None),
            ("Don't show me exams, just tell me what I'm doing today.",
             "schedule_query", "today", True, False, "today", None),
            ("I've got something important coming up and I'm free after dinner. What should I focus on?",
             "study_planning", "today", True, True, "today", "upcoming"),
        )
        for message, intent, time_scope, activities, exams, activity_scope, exam_scope in cases:
            with self.subTest(message=message):
                client = Mock()
                client.responses.parse.return_value = SimpleNamespace(
                    status="completed",
                    output_parsed={
                        "intent": intent, "time_scope": time_scope,
                        "include_activities": activities, "include_exams": exams,
                        "confidence": "high",
                    },
                )
                classification = ai_intent_classifier.classify_agent_intent(
                    client, message, [], ai_proposal.PROPOSAL_MODEL,
                )
                selected = ai_intent_classifier.context_from_classification(classification)
                self.assertEqual(selected, {
                    "activities_scope": activity_scope,
                    "include_exams": exams,
                    "exam_scope": exam_scope,
                })
                classifier_input = json.loads(
                    client.responses.parse.call_args.kwargs["input"][0]["content"]
                )
                self.assertEqual(classifier_input["current_message"], message)

    def test_classifier_schema_rejects_unknown_values_and_non_booleans(self):
        valid = {
            "intent": "schedule_query", "time_scope": "week",
            "include_activities": True, "include_exams": False,
            "confidence": "high",
        }
        self.assertEqual(ai_intent_classifier.validate_intent_classification(valid).model_dump(), {
            **valid, "memory": None, "exam_scope": None, "files": None,
        })
        invalid = (
            {**valid, "intent": "career_advice"},
            {**valid, "time_scope": "year"},
            {**valid, "include_activities": "true"},
            {**valid, "include_exams": 0},
            {**valid, "confidence": "maybe"},
            {**valid, "message": "Here is your answer"},
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ai_intent_classifier.validate_intent_classification(value)

    def test_classification_maps_all_and_unspecified_scopes(self):
        cases = (
            ("activity_query", "all", True, False, "all", None),
            ("general_question", "unspecified", False, False, None, None),
            ("exam_query", "today", False, True, None, "today"),
            ("study_planning", "unspecified", True, True, "today", "upcoming"),
        )
        for intent, time_scope, activities, exams, activity_scope, exam_scope in cases:
            with self.subTest(intent=intent, time_scope=time_scope):
                selected = ai_intent_classifier.context_from_classification({
                    "intent": intent, "time_scope": time_scope,
                    "include_activities": activities, "include_exams": exams,
                })
                self.assertEqual(selected, {
                    "activities_scope": activity_scope,
                    "include_exams": exams,
                    "exam_scope": exam_scope,
                })

    def test_general_question_can_independently_require_schedule_context(self):
        for activities in (True, False):
            with self.subTest(include_activities=activities):
                classification = ai_intent_classifier.validate_intent_classification({
                    "intent": "general_question", "time_scope": "tomorrow",
                    "include_activities": activities, "include_exams": False,
                    "memory": None, "confidence": "high",
                })
                selected = ai_intent_classifier.context_from_classification(classification)
                self.assertEqual(selected, {
                    "activities_scope": "tomorrow" if activities else None,
                    "include_exams": False, "exam_scope": None,
                })

    def test_classifier_uses_only_brief_history_and_no_observations(self):
        history = [
            {
                "user": f"Earlier request {number}",
                "assistant": {"message": f"Earlier reply {number}", "actions": [activity_action()]},
            }
            for number in range(1, 6)
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed={
                "intent": "study_planning", "time_scope": "today",
                "include_activities": True, "include_exams": True,
                "confidence": "high",
            },
        )
        ai_intent_classifier.classify_agent_intent(client, "Make it later.", history, "test-model")
        request = client.responses.parse.call_args.kwargs
        classifier_input = json.loads(request["input"][0]["content"])
        self.assertEqual(classifier_input["current_message"], "Make it later.")
        self.assertEqual([turn["user"] for turn in classifier_input["recent_conversation"]],
                         ["Earlier request 4", "Earlier request 5"])
        self.assertEqual(classifier_input["recent_conversation"][-1]["assistant"], "Earlier reply 5")
        self.assertNotIn("observations", classifier_input)
        self.assertNotIn("actions", request["input"][0]["content"])
        self.assertEqual(request["text_format"], ai_intent_classifier.AgentIntentClassification)
        self.assertEqual(request["model"], "test-model")
        self.assertFalse(request["store"])

    def test_confident_stage_one_skips_both_models(self):
        message = "What exams do I have this month?"
        with patch.object(ai_routing_pipeline, "classify_agent_intent") as stage_two, \
                patch.object(ai_routing_pipeline, "classify_stage_three") as stage_three:
            selected = ai_routing_pipeline.select_agent_context(Mock(), message, [], "stage-two-model")
        self.assertEqual(selected, {
            "activities_scope": None, "include_exams": True, "exam_scope": "month",
        })
        stage_two.assert_not_called()
        stage_three.assert_not_called()

    def test_confident_stage_two_skips_stage_three(self):
        message = "Don't show me exams, just tell me what I'm doing today."
        self.assertEqual(ai_context_router.assess_stage_one(message)["reason"],
                         "negated_exam_reference")
        decision = ai_intent_classifier.AgentIntentClassification(
            intent="schedule_query", time_scope="today",
            include_activities=True, include_exams=False, confidence="high",
        )
        with patch.object(ai_routing_pipeline, "classify_agent_intent", return_value=decision) as stage_two, \
                patch.object(ai_routing_pipeline, "classify_stage_three") as stage_three:
            selected = ai_routing_pipeline.select_agent_context(Mock(), message, [], "stage-two-model")
        self.assertEqual(selected, {
            "activities_scope": "today", "include_exams": False, "exam_scope": None,
        })
        stage_two.assert_called_once()
        stage_three.assert_not_called()

    def test_uncertain_stage_two_calls_stage_three_once(self):
        message = "Can you help with that thing we were discussing before, but not the other stuff?"
        history = [{"user": "Plan my schedule", "assistant": {"message": "Let's look at it.", "actions": []}}]
        uncertain = ai_intent_classifier.AgentIntentClassification(
            intent="general_question", time_scope="unspecified",
            include_activities=False, include_exams=False, confidence="low",
        )
        decision = ai_intent_classifier.AgentRoutingDecision(
            intent="schedule_query", time_scope="week",
            include_activities=True, include_exams=False,
        )
        with patch.object(ai_routing_pipeline, "classify_agent_intent", return_value=uncertain), \
                patch.object(ai_routing_pipeline, "classify_stage_three", return_value=decision) as stage_three:
            selected = ai_routing_pipeline.select_agent_context(
                Mock(), message, history, "stage-two-model",
            )
        self.assertEqual(selected, {
            "activities_scope": "week", "include_exams": False, "exam_scope": None,
        })
        stage_three.assert_called_once()
        stage_one_input = stage_three.call_args.args[3]
        stage_two_input = stage_three.call_args.args[4]
        self.assertFalse(stage_one_input["confident"])
        self.assertEqual(stage_two_input["reason"], "low_confidence")
        self.assertEqual(stage_two_input["classification"]["confidence"], "low")

    def test_invalid_stage_two_reaches_stage_three(self):
        message = "I've got a lot happening soon and don't know what to look at."
        decision = ai_intent_classifier.AgentRoutingDecision(
            intent="study_planning", time_scope="today",
            include_activities=True, include_exams=True,
        )
        with patch.object(ai_routing_pipeline, "classify_agent_intent", side_effect=ValueError("invalid")), \
                patch.object(ai_routing_pipeline, "classify_stage_three", return_value=decision) as stage_three:
            selected = ai_routing_pipeline.select_agent_context(Mock(), message, [], "stage-two-model")
        self.assertEqual(selected, {
            "activities_scope": "today", "include_exams": True, "exam_scope": "upcoming",
        })
        self.assertEqual(stage_three.call_args.args[4]["reason"], "invalid_or_unavailable")

    def test_invalid_converted_stage_two_context_reaches_stage_three(self):
        stage_two = ai_intent_classifier.AgentIntentClassification(
            intent="general_question", time_scope="tomorrow",
            include_activities=True, include_exams=False, confidence="high",
        )
        stage_three = ai_intent_classifier.AgentRoutingDecision(
            intent="general_question", time_scope="tomorrow",
            include_activities=True, include_exams=False,
        )
        malformed_selections = (
            {"activities_scope": "year", "include_exams": False, "exam_scope": None},
            {"activities_scope": "tomorrow", "include_exams": True, "exam_scope": None},
            {"activities_scope": "tomorrow", "include_exams": "false", "exam_scope": None},
        )
        expected = {"activities_scope": "tomorrow", "include_exams": False, "exam_scope": None}
        unresolved = {"selection": expected, "confident": False, "reason": "test_unresolved"}
        for malformed in malformed_selections:
            with self.subTest(selection=malformed), \
                    patch.object(ai_routing_pipeline, "assess_stage_one", return_value=unresolved), \
                    patch.object(ai_routing_pipeline, "classify_agent_intent", return_value=stage_two) as classifier, \
                    patch.object(ai_routing_pipeline, "context_from_classification", side_effect=[malformed, expected]), \
                    patch.object(ai_routing_pipeline, "classify_stage_three", return_value=stage_three) as fallback:
                trace = {}
                selected = ai_routing_pipeline.select_agent_context(
                    Mock(), "When should I wake up tomorrow?", [], "stage-two-model", trace=trace,
                )
                self.assertEqual(selected, expected)
                self.assertEqual(trace["stage"], "stage_3")
                classifier.assert_called_once()
                fallback.assert_called_once()
                self.assertEqual(fallback.call_args.args[4]["reason"], "invalid_or_unavailable")

    def test_stage_three_uses_only_routing_data_and_rejects_actions(self):
        history = [{"user": "Previous question", "assistant": {"message": "Previous reply", "actions": []}}]
        stage_one = {"selection": ai_context_router.choose_agent_context("Make it later."),
                     "confident": False, "reason": "no_meaningful_keyword_match"}
        stage_two = {"classification": None, "reason": "invalid_or_unavailable"}
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed={
                "intent": "study_planning", "time_scope": "today",
                "include_activities": True, "include_exams": True,
                "actions": [{"tool": "add_activity"}],
            },
        )
        with self.assertRaises(ValueError):
            ai_stage_three_router.classify_stage_three(
                client, "Make it later.", history, stage_one, stage_two,
            )
        request = client.responses.parse.call_args.kwargs
        routing_input = json.loads(request["input"][0]["content"])
        self.assertEqual(set(routing_input), {
            "current_message", "recent_conversation", "stage_1", "stage_2",
        })
        self.assertNotIn("observations", request["input"][0]["content"])
        self.assertNotIn("tools", request)
        self.assertEqual(request["text_format"], ai_intent_classifier.AgentRoutingDecision)
        self.assertEqual(request["model"], "gpt-6-sol")
        self.assertEqual(request["reasoning"], {"effort": "xhigh"})

    def test_stage_three_returns_only_valid_routing_metadata(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            status="completed",
            output_parsed={
                "intent": "activity_query", "time_scope": "week",
                "include_activities": True, "include_exams": False,
            },
        )
        decision = ai_stage_three_router.classify_stage_three(
            client, "Help with that schedule thing.", [],
            {"selection": None, "confident": False, "reason": "no_meaningful_keyword_match"},
            {"classification": None, "reason": "invalid_or_unavailable"},
        )
        self.assertEqual(decision.model_dump(), {
            "intent": "activity_query", "time_scope": "week",
            "include_activities": True, "include_exams": False,
            "exam_scope": None,
            "memory": None,
            "files": None,
        })

    def test_stage_three_schema_rejects_invalid_or_action_fields(self):
        valid = {
            "intent": "study_planning", "time_scope": "today",
            "include_activities": True, "include_exams": True,
        }
        for invalid in (
            {**valid, "intent": "unsupported"},
            {**valid, "time_scope": "year"},
            {**valid, "include_activities": "true"},
            {**valid, "include_exams": 1},
            {**valid, "tool": "add_activity"},
            {**valid, "actions": []},
            {**valid, "message": "Here is my advice"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    ai_intent_classifier.validate_routing_decision(invalid)

    def test_invalid_confident_stage_one_does_not_skip_stage_two(self):
        malformed = {
            "selection": {"activities_scope": "year", "include_exams": False, "exam_scope": None},
            "confident": True, "reason": None,
        }
        decision = ai_intent_classifier.AgentIntentClassification(
            intent="schedule_query", time_scope="week",
            include_activities=True, include_exams=False, confidence="high",
        )
        with patch.object(ai_routing_pipeline, "assess_stage_one", return_value=malformed), \
                patch.object(ai_routing_pipeline, "classify_agent_intent", return_value=decision) as stage_two, \
                patch.object(ai_routing_pipeline, "classify_stage_three") as stage_three:
            selected = ai_routing_pipeline.select_agent_context(Mock(), "This week", [], "stage-two-model")
        self.assertEqual(selected["activities_scope"], "week")
        stage_two.assert_called_once()
        stage_three.assert_not_called()

    def test_stage_three_failure_uses_safe_context_without_looping(self):
        message = "I'm overwhelmed; what should I be looking at?"
        with patch.object(ai_routing_pipeline, "classify_agent_intent", side_effect=RuntimeError("down")) as stage_two, \
                patch.object(ai_routing_pipeline, "classify_stage_three", side_effect=ValueError("invalid")) as stage_three:
            selected = ai_routing_pipeline.select_agent_context(Mock(), message, [], "stage-two-model")
        self.assertEqual(selected, ai_routing_pipeline.SAFE_MINIMAL_CONTEXT)
        stage_two.assert_called_once()
        stage_three.assert_called_once()

    def test_stage_two_controls_main_context_and_preserves_five_turns(self):
        history = [
            {"user": f"Turn {number}", "assistant": {"message": f"Reply {number}", "actions": []}}
            for number in range(1, 6)
        ]
        message = "Don't show me exams, just tell me what I'm doing today."
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value={"today": []}) as activities, \
                patch.object(ai_proposal, "build_exam_observation") as exams, \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.side_effect = [
                SimpleNamespace(status="completed", output_parsed={
                    "intent": "schedule_query", "time_scope": "today",
                    "include_activities": True, "include_exams": False,
                    "confidence": "high",
                }),
                SimpleNamespace(status="completed", output_parsed={"message": "Your schedule", "actions": []}),
            ]
            result = ai_proposal.get_agent_proposal(Mock(), message, history)
            calls = client.responses.parse.call_args_list

        self.assertEqual(result, {
            "message": "Your schedule", "actions": [], "memory_request": None, "missing_context": [],
        })
        self.assertEqual(len(calls), 2)
        classifier_input = json.loads(calls[0].kwargs["input"][0]["content"])
        self.assertNotIn("observations", classifier_input)
        self.assertEqual(len(classifier_input["recent_conversation"]), 2)
        main_messages = calls[1].kwargs["input"]
        self.assertEqual(len(main_messages), 11)
        self.assertEqual(main_messages[0], {"role": "user", "content": "Turn 1"})
        self.assertEqual(json.loads(main_messages[1]["content"])["message"], "Reply 1")
        main_input = json.loads(main_messages[-1]["content"])
        self.assertEqual(main_input["request"], message)
        self.assertEqual(main_input["observations"], {"activities": {"today": []}})
        activities.assert_called_once_with(ANY, scope="today")
        exams.assert_not_called()

    def test_context_router_examples(self):
        cases = (
            ("What should I do today?", "today", False, None),
            ("What should I study tonight?", "today", True, "upcoming"),
            ("What do I have this week?", "this_week", False, None),
            ("What am I doing this month?", "month", False, None),
            ("What exams do I have?", None, True, "upcoming"),
            ("What exams do I have this month?", None, True, "month"),
            ("Show me all activities.", "all", False, None),
            ("Look at all my activities and exams.", "all", True, "upcoming"),
            ("What should I do today for my exams?", "today", True, "upcoming"),
            ("Everything on my calendar", "all", False, None),
            ("Show my full calendar", "all", False, None),
            ("Show my entire schedule", "all", False, None),
            ("Look at everything", "all", True, "upcoming"),
            ("What are my upcoming quizzes?", None, True, "upcoming"),
            ("What is coming in the next few days?", "week", False, None),
            ("What is due later this month?", "month", False, None),
            ("TODAY’S schedule", "today", False, None),
            ("Help me plan", "today", True, "upcoming"),
        )
        for message, activity_scope, include_exams, exam_scope in cases:
            with self.subTest(message=message):
                self.assertEqual(ai_context_router.choose_agent_context(message), {
                    "activities_scope": activity_scope,
                    "include_exams": include_exams,
                    "exam_scope": exam_scope,
                })

    def test_today_observation_does_not_send_later_dates(self):
        today = date(2026, 9, 29)
        occurrence = {
            "id": 1, "name": "Lecture", "start_time": "11:00",
            "end_time": "12:00", "calendar_date": "2026-09-29",
        }
        tomorrow = {**occurrence, "calendar_date": "2026-09-30"}
        connection = Mock()
        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", return_value=[occurrence, tomorrow]) as week:
            result = activity_observation.build_activity_observation(connection, scope="today")

        week.assert_called_once_with(connection, today)
        self.assertEqual(result["today"], [{"name": "Lecture", "start": "11:00", "end": "12:00"}])
        self.assertNotIn("upcoming_7d", result)

    def test_week_observation_uses_the_next_seven_dates(self):
        today = date(2026, 9, 29)
        occurrence = {
            "id": 1, "name": "Study", "start_time": None, "end_time": None,
            "calendar_date": "2026-10-05",
        }
        too_late = {**occurrence, "calendar_date": "2026-10-06"}
        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", return_value=[occurrence, too_late]):
            result = activity_observation.build_activity_observation(Mock(), scope="week")
        self.assertEqual(result["upcoming_7d"], [
            {"name": "Study", "date": "2026-10-05", "start": None, "end": None},
        ])

    def test_month_observation_uses_calendar_recurrence_and_stops_at_month_end(self):
        today = date(2026, 9, 1)
        starts = []

        def calendar_occurrences(_connection, week_start):
            starts.append(week_start)
            if week_start == date(2026, 9, 29):
                return [
                    {"id": 1, "name": "Month end", "calendar_date": "2026-09-30",
                     "start_time": None, "end_time": None},
                    {"id": 2, "name": "Next month", "calendar_date": "2026-10-01",
                     "start_time": None, "end_time": None},
                ]
            return []

        with patch.object(activity_observation, "get_current_date", return_value=today), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)), \
                patch.object(activity_observation, "get_week_activities", side_effect=calendar_occurrences):
            result = activity_observation.build_activity_observation(Mock(), scope="month")

        self.assertEqual(starts, [date(2026, 9, day) for day in (1, 8, 15, 22, 29)])
        self.assertEqual(result["upcoming_month"], [
            {"name": "Month end", "date": "2026-09-30", "start": None, "end": None},
        ])

    def test_month_observation_uses_real_calendar_recurrence_rules(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("""
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY, name TEXT, category TEXT, subject TEXT,
                activity_type TEXT, date TEXT, weekday TEXT, start_time TEXT,
                end_time TEXT, active_start_date TEXT, active_end_date TEXT
            )
        """)
        connection.executemany(
            """INSERT INTO activities
               (name, category, activity_type, date, weekday, start_time, end_time)
               VALUES (?, 'Study', ?, ?, ?, NULL, NULL)""",
            [
                ("Daily", "daily", None, None),
                ("Weekly", "weekly", None, "Wednesday"),
                ("September task", "one_time", "2026-09-30", None),
                ("October task", "one_time", "2026-10-01", None),
            ],
        )
        with patch.object(activity_observation, "get_current_date", return_value=date(2026, 9, 29)), \
                patch.object(activity_observation, "get_current_time", return_value="09:00"), \
                patch.object(activity_observation, "get_current_and_next_activities", return_value=([], None)):
            result = activity_observation.build_activity_observation(connection, scope="month")

        self.assertEqual(
            [(item["name"], item["date"]) for item in result["upcoming_month"]],
            [
                ("Daily", "2026-09-29"),
                ("Daily", "2026-09-30"),
                ("September task", "2026-09-30"),
                ("Weekly", "2026-09-30"),
            ],
        )

    def test_all_activity_scope_uses_existing_activity_rows(self):
        activity = (1, "Lecture", "University", "COMPSCI 130", "weekly",
                    None, "Monday", "10:00", "11:00", "2026-07-01", "2026-11-01")
        with patch.object(activity_observation, "get_all_activities", return_value=[activity]), \
                patch.object(activity_observation, "get_week_activities") as week:
            result = activity_observation.build_activity_observation(Mock(), scope="all")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["all_activities"][0]["weekday"], "Monday")
        self.assertEqual(result["all_activities"][0]["active_end_date"], "2026-11-01")
        week.assert_not_called()

    def test_exam_month_scope_uses_same_date_boundaries(self):
        exams = [
            (1, "September test", "Test", "COMPSCI", "2026-09-30", None, None),
            (2, "October test", "Test", "COMPSCI", "2026-10-01", None, None),
        ]
        with patch.object(exam_observation, "get_current_date", return_value=date(2026, 9, 29)), \
                patch.object(exam_observation, "get_current_time", return_value="09:00"), \
                patch.object(exam_observation, "get_all_exams", return_value=exams):
            result = exam_observation.build_exam_observation(Mock(), scope="month")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["upcoming"][0]["date"], "2026-09-30")

    def test_request_builds_only_selected_observations(self):
        cases = (
            ("What do I have this week?", "this_week", None),
            ("What exams do I have this month?", None, "month"),
            ("Look at all my activities and exams.", "all", "upcoming"),
        )
        for message, activity_scope, exam_scope in cases:
            with self.subTest(message=message), \
                    patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                    patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                    patch.object(ai_proposal, "build_activity_observation", return_value={"activity_data": True}) as activity_builder, \
                    patch.object(ai_proposal, "build_exam_observation", return_value={"exam_data": True}) as exam_builder, \
                    patch.object(ai_proposal, "OpenAI") as client_class:
                client = client_class.return_value.__enter__.return_value
                client.responses.parse.return_value = SimpleNamespace(
                    status="completed", output_parsed={"message": "Reply", "actions": []},
                )
                ai_proposal.get_agent_proposal(Mock(), message)
                payload = json.loads(client.responses.parse.call_args.kwargs["input"][-1]["content"])
                if activity_scope is None:
                    activity_builder.assert_not_called()
                    self.assertNotIn("activities", payload["observations"])
                else:
                    activity_builder.assert_called_once_with(ANY, scope=activity_scope)
                    self.assertIn("activities", payload["observations"])
                if exam_scope is None:
                    exam_builder.assert_not_called()
                    self.assertNotIn("exams", payload["observations"])
                else:
                    exam_builder.assert_called_once_with(ANY, scope=exam_scope)
                    self.assertIn("exams", payload["observations"])

    def test_only_the_last_five_completed_turns_are_kept(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}):
            archive_file = ai_memory.ARCHIVE_FILE
            for number in range(1, 6):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            first_five = ai_memory.get_recent_turns("session-one")
            self.assertEqual([turn["user"] for turn in first_five],
                             [f"Turn {number}" for number in range(1, 6)])
            self.assertEqual(first_five[0]["assistant"]["message"], "Reply 1")
            self.assertFalse(archive_file.exists())

            ai_memory.add_completed_turn(
                "session-one", "Turn 6", {"message": "Reply 6", "actions": []},
            )
            latest_five = ai_memory.get_recent_turns("session-one")
            self.assertEqual([turn["user"] for turn in latest_five],
                             [f"Turn {number}" for number in range(2, 7)])
            self.assertEqual([turn["assistant"]["message"] for turn in latest_five],
                             [f"Reply {number}" for number in range(2, 7)])
            archived = [json.loads(line) for line in archive_file.read_text().splitlines()]
            self.assertEqual([item["turn"]["user"] for item in archived], ["Turn 1"])
            self.assertEqual(archived[0]["turn"]["assistant"]["message"], "Reply 1")
            self.assertEqual(archive_file.stat().st_mode & 0o777, 0o600)

            ai_memory.add_completed_turn(
                "session-one", "Turn 7", {"message": "Reply 7", "actions": []},
            )
            self.assertEqual(
                [turn["user"] for turn in ai_memory.get_recent_turns("session-one")],
                [f"Turn {number}" for number in range(3, 8)],
            )
            archived = [json.loads(line) for line in archive_file.read_text().splitlines()]
            self.assertEqual([item["turn"]["user"] for item in archived], ["Turn 1", "Turn 2"])
            self.assertEqual([item["session_id"] for item in archived], ["session-one"] * 2)

    def test_raised_and_lowered_limit_archives_without_losing_turns(self):
        selected_limit = [10]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "get_max_recent_turns", side_effect=lambda: selected_limit[0]):
            for number in range(1, 11):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            self.assertEqual(len(ai_memory.get_recent_turns("session-one")), 10)
            self.assertFalse(ai_memory.ARCHIVE_FILE.exists())

            selected_limit[0] = 5
            ai_memory.enforce_recent_limit("session-one")
            recent = ai_memory.get_recent_turns("session-one")
            self.assertEqual([turn["user"] for turn in recent], [f"Turn {n}" for n in range(6, 11)])
            ai_memory.add_completed_turn(
                "session-one", "Turn 11", {"message": "Reply 11", "actions": []},
            )
            archived = [json.loads(line) for line in ai_memory.ARCHIVE_FILE.read_text().splitlines()]
            self.assertEqual([row["turn"]["user"] for row in archived], [f"Turn {n}" for n in range(1, 7)])
            self.assertTrue(all(row.get("timestamp") for row in archived))
            self.assertEqual(
                [turn["user"] for turn in ai_memory.get_recent_turns("session-one")],
                [f"Turn {n}" for n in range(7, 12)],
            )

    def test_limit_can_retain_one_hundred_turns(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "get_max_recent_turns", return_value=100):
            for number in range(1, 102):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            recent = ai_memory.get_recent_turns("session-one")
            archived = [json.loads(line) for line in ai_memory.ARCHIVE_FILE.read_text().splitlines()]

        self.assertEqual(len(recent), 100)
        self.assertEqual(recent[0]["user"], "Turn 2")
        self.assertEqual(recent[-1]["user"], "Turn 101")
        self.assertEqual([row["turn"]["user"] for row in archived], ["Turn 1"])

    def test_saved_limit_controls_the_real_archive_window(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_config, "AI_ENV_FILE", Path(directory) / ".env"), \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "get_max_recent_turns", wraps=ai_config.get_max_recent_turns), \
                patch.dict(ai_config.os.environ, {ai_config.RECENT_TURNS_ENV_KEY: "5"}):
            ai_config.save_max_recent_turns(6)
            for number in range(1, 8):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            recent = ai_memory.get_recent_turns("session-one")
            archived = [json.loads(line) for line in ai_memory.ARCHIVE_FILE.read_text().splitlines()]

        self.assertEqual([turn["user"] for turn in recent], [f"Turn {n}" for n in range(2, 8)])
        self.assertEqual([row["turn"]["user"] for row in archived], ["Turn 1"])

    def test_empty_archive_is_appended_and_archived_turns_are_not_sent(self):
        secret = "sk-proj-" + "A" * 24
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}):
            ai_memory.ARCHIVE_FILE.touch()
            for number in range(1, 8):
                reply = f"Reply {number}"
                if number == 1:
                    reply += f" {secret}"
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}", {"message": reply, "actions": []},
                )
            recent = ai_memory.get_recent_turns("session-one")
            archived_text = ai_memory.ARCHIVE_FILE.read_text()
            archived = [json.loads(line) for line in archived_text.splitlines()]

        self.assertEqual([turn["user"] for turn in recent], ["Turn 3", "Turn 4", "Turn 5", "Turn 6", "Turn 7"])
        self.assertEqual([item["turn"]["user"] for item in archived], ["Turn 1", "Turn 2"])
        self.assertNotIn(secret, archived_text)
        self.assertIn("[redacted API key]", archived[0]["turn"]["assistant"]["message"])

        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value={"today": []}), \
                patch.object(ai_proposal, "build_exam_observation", return_value={"upcoming": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={"message": "Plan", "actions": []},
            )
            ai_proposal.get_agent_proposal(Mock(), "What should I study tonight?", recent)
            messages = client.responses.parse.call_args.kwargs["input"]

        self.assertEqual(
            [message["content"] for message in messages if message["role"] == "user"][:-1],
            ["Turn 3", "Turn 4", "Turn 5", "Turn 6", "Turn 7"],
        )
        self.assertNotIn("Turn 1", str(messages))
        self.assertNotIn("Turn 2", str(messages))

    def test_archive_failure_does_not_drop_the_oldest_turn(self):
        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(ai_memory, "_archive_turn", side_effect=OSError("archive unavailable")):
            for number in range(1, 6):
                ai_memory.add_completed_turn(
                    "session-one", f"Turn {number}",
                    {"message": f"Reply {number}", "actions": []},
                )
            with self.assertRaisesRegex(OSError, "archive unavailable"):
                ai_memory.add_completed_turn(
                    "session-one", "Turn 6", {"message": "Reply 6", "actions": []},
                )
            self.assertEqual(
                [turn["user"] for turn in ai_memory.get_recent_turns("session-one")],
                ["Turn 1", "Turn 2", "Turn 3", "Turn 4", "Turn 5"],
            )

    def test_message_only_is_valid(self):
        result = ai_proposal.validate_agent_proposal({
            "message": "No extra study session is needed.",
            "actions": [],
        })
        self.assertEqual(result.model_dump()["actions"], [])
        self.assertIsNone(result.memory_request)

    def test_memory_request_supports_time_topic_and_both(self):
        cases = (
            ({"time_reference": "yesterday", "search_terms": []},
             "yesterday", []),
            ({"time_reference": None, "search_terms": ["screen time"]},
             None, ["screen time"]),
            ({"time_reference": "last_week", "search_terms": ["COMPSCI", "study plan"]},
             "last_week", ["COMPSCI", "study plan"]),
            ({"time_reference": "unspecified", "search_terms": []},
             "unspecified", []),
        )
        for request, time_reference, terms in cases:
            with self.subTest(request=request):
                result = ai_proposal.validate_agent_proposal({
                    "message": "I need to look up that earlier conversation.",
                    "actions": [], "memory_request": request,
                })
                self.assertEqual(result.memory_request.time_reference, time_reference)
                self.assertEqual(result.memory_request.search_terms, terms)

    def test_invalid_memory_requests_are_rejected(self):
        invalid_requests = (
            {"time_reference": "last_year", "search_terms": ["COMPSCI"]},
            {"time_reference": "2026-09-30", "search_terms": []},
            {"time_reference": None, "search_terms": ["what did we about"]},
            {"time_reference": None, "search_terms": [" "]},
            {"time_reference": None, "search_terms": list("abcdef")},
            {"time_reference": None, "search_terms": "COMPSCI"},
            {"time_reference": None, "search_terms": [123]},
            {"time_reference": "yesterday", "search_terms": [], "archive_content": "made up"},
            {"search_terms": ["COMPSCI"]},
        )
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(ai_proposal.InvalidProposalError):
                    ai_proposal.validate_agent_proposal({
                        "message": "I need to look that up.",
                        "actions": [], "memory_request": request,
                    })

    def test_model_can_return_memory_request_without_reading_archive(self):
        expected_request = {"time_reference": "last_week", "search_terms": ["COMPSCI"]}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "select_agent_context", return_value={
                    "activities_scope": None, "include_exams": False, "exam_scope": None,
                }), \
                patch.object(ai_proposal, "OpenAI") as client_class, \
                patch.object(ai_memory, "_archive_turn") as archive:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={
                    "message": "I need to look up that earlier conversation.",
                    "actions": [], "memory_request": expected_request,
                },
            )
            result = ai_proposal.get_agent_proposal(
                Mock(), "What did we talk about last week about COMPSCI?",
            )
            request = client.responses.parse.call_args.kwargs

        self.assertEqual(result["memory_request"], expected_request)
        self.assertEqual(result["actions"], [])
        self.assertEqual(request["text_format"], ai_proposal.AgentProposal)
        self.assertNotIn("archived", str(request["input"]))
        archive.assert_not_called()

    def test_add_activity_proposal_is_valid(self):
        result = ai_proposal.validate_agent_proposal({
            "message": "I suggest a revision session.",
            "actions": [activity_action()],
        })
        self.assertEqual(result.actions[0].arguments.date, "2026-09-26")

    def test_daily_and_weekly_proposals_are_valid(self):
        for action in (
            activity_action(activity_type="daily", date=None, weekday=None),
            activity_action(activity_type="weekly", date=None, weekday="Monday"),
        ):
            with self.subTest(activity_type=action["arguments"]["activity_type"]):
                result = ai_proposal.validate_agent_proposal({
                    "message": "I suggest this activity.", "actions": [action],
                })
                self.assertEqual(result.actions[0].arguments.activity_type,
                                 action["arguments"]["activity_type"])

    def test_unknown_tools_and_bad_activity_data_are_rejected(self):
        invalid_actions = [
            {**activity_action(), "tool": "delete_activity"},
            {**activity_action(), "tool": "add_exam"},
            activity_action(date="2026-02-30"),
            activity_action(start_time="25:00"),
            activity_action(start_time="19:00", end_time="18:00"),
            activity_action(activity_type="weekly", date=None, weekday="Funday"),
            activity_action(activity_type="daily", date="2026-09-26"),
            activity_action(name=" "),
            {**activity_action(), "arguments": {**activity_action()["arguments"], "sql": "DELETE"}},
        ]
        for action in invalid_actions:
            with self.subTest(action=action):
                with self.assertRaises(ai_proposal.InvalidProposalError):
                    ai_proposal.validate_agent_proposal({"message": "Plan", "actions": [action]})

    def test_missing_fields_and_empty_message_are_rejected(self):
        with self.assertRaises(ai_proposal.InvalidProposalError):
            ai_proposal.validate_agent_proposal({"message": " ", "actions": []})
        incomplete = activity_action()
        del incomplete["arguments"]["category"]
        with self.assertRaises(ai_proposal.InvalidProposalError):
            ai_proposal.validate_agent_proposal({"message": "Plan", "actions": [incomplete]})

    def test_model_receives_separate_observations_and_returns_proposal(self):
        expected = {"message": "No change needed.", "actions": [], "memory_request": None, "missing_context": []}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value={"today": []}), \
                patch.object(ai_proposal, "build_exam_observation", return_value={"upcoming": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed=expected,
            )
            result = ai_proposal.get_agent_proposal(Mock(), "Help me plan tonight")
            request = client.responses.parse.call_args.kwargs

        self.assertEqual(result, expected)
        self.assertEqual(request["text_format"], ai_proposal.AgentProposal)
        self.assertEqual(request["instructions"], ai_proposal.STUDY_PLANNING_INSTRUCTIONS)
        self.assertFalse(request["store"])
        model_input = json.loads(request["input"][0]["content"])
        self.assertEqual(model_input["request"], "Help me plan tonight")
        self.assertEqual(model_input["observations"], {
            "activities": {"today": []}, "exams": {"upcoming": []},
        })

    def test_saved_model_and_effort_apply_only_to_main_agent(self):
        selection = {
            "activities_scope": "today", "include_exams": False, "exam_scope": None,
        }
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.object(ai_proposal, "get_agent_model_settings", return_value={
                    "model": "gpt-6-astra", "reasoning_effort": "high",
                }), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "select_agent_context", return_value=selection) as router, \
                patch.object(ai_proposal, "build_activity_observation", return_value={"today": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={"message": "You have time to study.", "actions": []},
            )
            ai_proposal.get_agent_proposal(Mock(), "What should I do today?")
            request = client.responses.parse.call_args.kwargs

        self.assertEqual(request["model"], "gpt-6-astra")
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertEqual(request["max_output_tokens"], 5000)
        self.assertEqual(router.call_args.args[-1], ai_proposal.PROPOSAL_MODEL)
        self.assertEqual(client_class.call_args.kwargs["timeout"], 180)

    def test_follow_up_receives_both_sides_of_the_turn_and_fresh_observations(self):
        history = [{
            "user": "Help me study tonight.",
            "assistant": {
                "message": "I suggest COMPSCI from 7–8 PM.",
                "actions": [activity_action(start_time="19:00", end_time="20:00")],
            },
        }]
        updated_observations = {"today": [], "upcoming_7d": []}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "build_activity_observation", return_value=updated_observations), \
                patch.object(ai_proposal, "build_exam_observation", return_value={"upcoming": []}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={"message": "What later time works?", "actions": []},
            )
            ai_proposal.get_agent_proposal(Mock(), "Make it later.", history)
            messages = client.responses.parse.call_args.kwargs["input"]

        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[0]["content"], "Help me study tonight.")
        earlier_reply = json.loads(messages[1]["content"])
        self.assertEqual(earlier_reply["message"], "I suggest COMPSCI from 7–8 PM.")
        self.assertEqual(earlier_reply["proposed_actions_not_executed"][0]["arguments"]["start_time"], "19:00")
        latest_request = json.loads(messages[2]["content"])
        self.assertEqual(latest_request["request"], "Make it later.")
        self.assertEqual(latest_request["observations"]["activities"], updated_observations)
        self.assertIn("trust the latest observations", ai_proposal.STUDY_PLANNING_INSTRUCTIONS)
        self.assertEqual(client.responses.parse.call_count, 3)

    def test_main_agent_uses_configured_recent_turn_limit(self):
        history = [
            {"user": f"Turn {number}", "assistant": {"message": f"Reply {number}", "actions": []}}
            for number in range(1, 9)
        ]
        selection = {"activities_scope": None, "include_exams": False, "exam_scope": None}
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=True), \
                patch.object(ai_proposal, "get_max_recent_turns", return_value=8), \
                patch.object(ai_proposal, "select_agent_context", return_value=selection), \
                patch.dict(ai_proposal.os.environ, {"OPENAI_API_KEY": "test-key"}), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed={"message": "Reply", "actions": []},
            )
            ai_proposal.get_agent_proposal(Mock(), "What should I do?", history)
            messages = client.responses.parse.call_args.kwargs["input"]

        self.assertEqual(len(messages), 17)
        self.assertEqual(messages[0], {"role": "user", "content": "Turn 1"})
        self.assertEqual(messages[-2]["role"], "assistant")
        self.assertEqual(json.loads(messages[-1]["content"])["request"], "What should I do?")

    def test_endpoint_session_keeps_five_completed_turns(self):
        connection = Mock()
        client = TestClient(api.app)
        histories = []

        def mock_proposal(_connection, message, recent_turns, *, session_id=None, include_context=False):
            histories.append(list(recent_turns))
            return {"message": f"Reply to {message}", "actions": []}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ai_memory, "ARCHIVE_FILE", Path(directory) / "archive.jsonl"), \
                patch.object(ai_memory, "_sessions", {}), \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=connection), \
                patch.object(api, "get_agent_proposal", side_effect=mock_proposal), \
                patch.object(api, "add_activity") as insert:
            for number in range(1, 7):
                response = client.post("/ai/propose", json={"message": f"Turn {number}"})
                self.assertEqual(response.status_code, 200)
                if number == 1:
                    self.assertIn("httponly", response.headers["set-cookie"].lower())
            session_id = client.cookies.get("ai_agent_session")
            stored = ai_memory.get_recent_turns(session_id)
            response = client.post("/ai/propose", json={"message": "Turn 7"})
            self.assertEqual(response.status_code, 200)
            archive_rows = [
                json.loads(line) for line in ai_memory.ARCHIVE_FILE.read_text().splitlines()
            ]

        self.assertEqual([len(history) for history in histories], [0, 1, 2, 3, 4, 5, 5])
        self.assertEqual([turn["user"] for turn in stored],
                         [f"Turn {number}" for number in range(2, 7)])
        self.assertEqual(stored[-1]["assistant"]["message"], "Reply to Turn 6")
        self.assertEqual([turn["user"] for turn in histories[-1]],
                         [f"Turn {number}" for number in range(2, 7)])
        self.assertEqual([item["turn"]["user"] for item in archive_rows],
                         ["Turn 1", "Turn 2"])
        insert.assert_not_called()
        self.assertEqual(connection.close.call_count, 7)

    def test_failed_proposal_does_not_create_a_completed_turn(self):
        client = TestClient(api.app)
        with patch.object(ai_memory, "_sessions", {}) as sessions, \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=Mock()), \
                patch.object(api, "get_agent_proposal", side_effect=ai_proposal.InvalidProposalError):
            response = client.post("/ai/propose", json={"message": "Plan tonight"})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(sessions, {})
            self.assertNotIn("ai_agent_session", client.cookies)

    def test_separate_browser_sessions_do_not_share_history(self):
        histories = []

        def mock_proposal(_connection, _message, recent_turns, *, session_id=None, include_context=False):
            histories.append(recent_turns)
            return {"message": "Reply", "actions": []}

        with patch.object(ai_memory, "_sessions", {}), \
                patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=Mock()), \
                patch.object(api, "get_agent_proposal", side_effect=mock_proposal):
            first_client = TestClient(api.app)
            second_client = TestClient(api.app)
            first_client.post("/ai/propose", json={"message": "First user's plan"})
            second_client.post("/ai/propose", json={"message": "Second user's plan"})

        self.assertEqual(histories, [[], []])
        self.assertNotEqual(first_client.cookies.get("ai_agent_session"),
                            second_client.cookies.get("ai_agent_session"))

    def test_instructions_keep_advice_and_actions_separate(self):
        instructions = ai_proposal.STUDY_PLANNING_INSTRUCTIONS
        for rule in (
            "study planning assistant",
            "activity and exam observations",
            "ask one simple follow-up question",
            "user-facing message",
            "separate actions list",
            "only allowed tool is add_activity",
            "Never execute a tool, generate SQL",
            '"message": "response for the user", "actions": []',
            '"memory_request": null',
            "Do not claim to remember or invent archived details",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, instructions)

    def test_missing_key_prevents_model_call(self):
        with patch.object(ai_proposal, "is_openai_api_key_configured", return_value=False), \
                patch.object(ai_proposal, "OpenAI") as client_class:
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                ai_proposal.get_agent_proposal(Mock(), "Plan tonight")
            client_class.assert_not_called()

    def test_endpoint_returns_proposal_without_inserting(self):
        expected = {"message": "I suggest revision.", "actions": [activity_action()]}
        connection = Mock()
        with patch.object(api, "is_openai_api_key_configured", return_value=True), \
                patch.object(api.sqlite3, "connect", return_value=connection) as connect, \
                patch.object(api, "get_agent_proposal", return_value=expected), \
                patch.object(api, "add_activity") as insert:
            response = TestClient(api.app).post(
                "/ai/propose", json={"message": "Plan two hours tonight"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertTrue(connect.call_args.kwargs["uri"])
        self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))
        connection.close.assert_called_once()
        insert.assert_not_called()

    def test_endpoint_rejects_missing_key_without_reading_database(self):
        with patch.object(api, "is_openai_api_key_configured", return_value=False), \
                patch.object(api.sqlite3, "connect") as connect:
            response = TestClient(api.app).post(
                "/ai/propose", json={"message": "Plan tonight"},
            )
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
