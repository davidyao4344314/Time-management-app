"""Small structured intent classifier with the keyword router as fallback."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.ai_context_router import choose_agent_context


CLASSIFIER_INSTRUCTIONS = """Classify what context a study assistant needs. Never answer, advise, plan, or request actions.

study_planning: what to focus on or how to use free time; usually needs activities and exams. schedule_query: schedule or availability. exam_query: assessments or deadlines. activity_query: activity details. general_question: none of these.

Read the whole current message, respect exclusions such as 'don't show exams', and use brief conversation only to resolve follow-ups. Tonight or after dinner means today when no other date is given. Use all only when explicitly requested; otherwise use unspecified if no time is implied. Exam-only queries need no activities. Return only intent, time_scope, include_activities, and include_exams."""


class AgentIntentClassification(BaseModel):
    """The only fields Stage 2 may return."""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal[
        "study_planning", "schedule_query", "exam_query",
        "activity_query", "general_question",
    ]
    time_scope: Literal["today", "week", "month", "all", "unspecified"]
    include_activities: bool
    include_exams: bool


def validate_intent_classification(value):
    """Reject unknown labels, non-booleans, and extra response fields."""
    return AgentIntentClassification.model_validate(value)


def classify_agent_intent(client, user_message, recent_turns, model):
    """Call the same OpenAI client with no activity or exam observations."""
    brief_history = [
        {
            "user": turn["user"][:300],
            "assistant": turn["assistant"]["message"][:300],
        }
        for turn in list(recent_turns or [])[-2:]
    ]
    classifier_input = {
        "recent_conversation": brief_history,
        "current_message": user_message,
    }
    response = client.responses.parse(
        model=model,
        instructions=CLASSIFIER_INSTRUCTIONS,
        input=[{"role": "user", "content": json.dumps(classifier_input, ensure_ascii=False)}],
        text_format=AgentIntentClassification,
        reasoning={"effort": "none"},
        max_output_tokens=160,
        store=False,
    )
    if response.status != "completed" or response.output_parsed is None:
        raise ValueError("The classifier did not return a complete result.")
    return validate_intent_classification(response.output_parsed)


def context_from_classification(value):
    """Translate Stage 2 into the Stage 1 selection shape used by builders."""
    classification = validate_intent_classification(value)
    scope = classification.time_scope
    activities_scope = ("today" if scope == "unspecified" else scope) \
        if classification.include_activities else None

    if not classification.include_exams:
        exam_scope = None
    elif scope in {"week", "month"}:
        exam_scope = scope
    elif scope == "today" and classification.intent == "exam_query" \
            and not classification.include_activities:
        exam_scope = "today"
    else:
        # Study planning can use upcoming exams even when activities are today.
        exam_scope = "upcoming"

    return {
        "activities_scope": activities_scope,
        "include_exams": classification.include_exams,
        "exam_scope": exam_scope,
    }


def select_agent_context(client, user_message, recent_turns, model):
    """Use semantic Stage 2 if valid; otherwise retain Stage 1 behavior."""
    try:
        classification = classify_agent_intent(client, user_message, recent_turns, model)
        return context_from_classification(classification)
    except Exception:
        # Only the classifier call/validation is inside this fallback boundary.
        return choose_agent_context(user_message)
