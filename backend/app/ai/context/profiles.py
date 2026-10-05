"""Translate routing classifications into observation-selection profiles."""

from backend.app.ai.context.contracts import AgentIntentClassification, validate_routing_decision


def context_from_classification(value):
    if isinstance(value, AgentIntentClassification):
        value = value.model_dump(exclude={"confidence"})
    classification = validate_routing_decision(value)
    scope = classification.time_scope
    activities_scope = ("today" if scope == "unspecified" else scope) \
        if classification.include_activities else None
    if not classification.include_exams:
        exam_scope = None
    elif classification.exam_scope is not None:
        exam_scope = classification.exam_scope
    elif classification.intent == "study_planning":
        exam_scope = "upcoming"
    elif scope in {"today", "week", "this_week", "next_week", "tomorrow", "month"}:
        exam_scope = scope
    else:
        exam_scope = "upcoming"
    return {
        "activities_scope": activities_scope,
        "include_exams": classification.include_exams,
        "exam_scope": exam_scope,
        **({"memory": classification.memory.model_dump()} if classification.memory is not None else {}),
        **({"files": classification.files.model_dump()} if classification.files is not None else {}),
    }
