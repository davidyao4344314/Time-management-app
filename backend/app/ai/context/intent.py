"""Small structured intent classifier with the keyword router as fallback."""

import json

CLASSIFIER_INSTRUCTIONS = """Classify what context a study assistant needs. Never answer, advise, plan, or request actions.

study_planning: what to focus on or how to use free time; usually needs activities and exams. schedule_query: schedule or availability. exam_query: assessments or deadlines. activity_query: activity details. general_question: none of these.

Read the whole current message, respect exclusions such as 'don't show exams', and use brief conversation only to resolve follow-ups. Tonight or after dinner means today when no other date is given. Use all only when explicitly requested; otherwise use unspecified if no time is implied. Exam-only queries need no activities. Set confidence to low only when you cannot reliably decide what information is needed; an ordinary general question can still be high confidence. Return only intent, time_scope, include_activities, include_exams, and confidence."""


MEMORY_ROUTING_INSTRUCTIONS = """ Also return memory: null unless older conversation is needed. Recent follow-ups already answered by recent context need no archive lookup. For recollection, return memory={sources:[...], query:{time_reference:..., search_terms:[...]}}. Allowed sources: raw_archive for exact prior wording, compressed_archive for past discussion summaries, durable for stated preferences/goals/decisions. Choose only relevant sources. Use symbolic time_reference today, yesterday, last_week, this_week, last_month, this_month, unspecified, or null; never calculate dates. Use at most five short topic terms. 'What did we discuss last week?' needs memory; 'What exams are next week?' and 'study before dinner' do not. Memory-only questions need no schedule observations; mixed planning requests may need both. Respect requests not to use history. Never return session IDs, paths, or retrieved content."""
CLASSIFIER_INSTRUCTIONS += MEMORY_ROUTING_INSTRUCTIONS

from backend.app.ai.context.contracts import (
    AgentRoutingDecision, AgentIntentClassification,
    validate_intent_classification, validate_routing_decision,
)


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
        max_output_tokens=400,
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
        **({"memory": classification.memory.model_dump()} if classification.memory is not None else {}),
    }
