"""Small structured intent classifier with the keyword router as fallback."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

CLASSIFIER_INSTRUCTIONS = """Classify what context a study assistant needs. Never answer, advise, plan, or request actions.

study_planning: what to focus on or how to use free time; usually needs activities and exams. schedule_query: schedule or availability. exam_query: assessments or deadlines. activity_query: activity details. general_question: none of these.

Read the whole current message, respect exclusions such as 'don't show exams', and use brief conversation only to resolve follow-ups. Tonight or after dinner means today when no other date is given. Use all only when explicitly requested; otherwise use unspecified if no time is implied. Exam-only queries need no activities. Set confidence to low only when you cannot reliably decide what information is needed; an ordinary general question can still be high confidence. Return only intent, time_scope, include_activities, include_exams, and confidence."""


class AgentRoutingDecision(BaseModel):
    """The four routing fields shared by Stage 2 and Stage 3."""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal[
        "study_planning", "schedule_query", "exam_query",
        "activity_query", "general_question",
    ]
    time_scope: Literal["today", "week", "month", "all", "unspecified"]
    include_activities: bool
    include_exams: bool


class AgentIntentClassification(AgentRoutingDecision):
    """Stage 2 adds only a confidence signal to the shared routing decision."""

    confidence: Literal["high", "low"]


def validate_intent_classification(value):
    """Reject unknown labels, non-booleans, and extra response fields."""
    return AgentIntentClassification.model_validate(value)


def validate_routing_decision(value):
    """Validate the four shared routing fields, including Stage 3 output."""
    return AgentRoutingDecision.model_validate(value)


def brief_recent_conversation(recent_turns):
    """Give routing models only two short completed turns, without actions."""
    return [
        {
            "user": turn["user"][:300],
            "assistant": turn["assistant"]["message"][:300],
        }
        for turn in list(recent_turns or [])[-2:]
    ]


def classify_agent_intent(client, user_message, recent_turns, model):
    """Call the same OpenAI client with no activity or exam observations."""
    classifier_input = {
        "recent_conversation": brief_recent_conversation(recent_turns),
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
    if isinstance(value, AgentIntentClassification):
        value = value.model_dump(exclude={"confidence"})
    classification = validate_routing_decision(value)
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
