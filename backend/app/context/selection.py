"""One-pass Stage 1 → Stage 2 → Stage 3 → safe fallback routing."""

from backend.app.context.keywords import assess_stage_one
from backend.app.context.intent import classify_agent_intent, context_from_classification
from backend.app.context.fallback import classify_stage_three


SAFE_MINIMAL_CONTEXT = {
    "activities_scope": "today",
    "include_exams": True,
    "exam_scope": "upcoming",
}


def _valid_context_selection(selection):
    """Do not short-circuit on a malformed Stage 1 result."""
    return (
        isinstance(selection, dict)
        and set(selection) == {"activities_scope", "include_exams", "exam_scope"}
        and selection["activities_scope"] in {None, "today", "week", "month", "all"}
        and type(selection["include_exams"]) is bool
        and selection["exam_scope"] in {None, "today", "week", "month", "upcoming"}
        and (selection["exam_scope"] is not None) == selection["include_exams"]
    )


def select_agent_context(client, user_message, recent_turns, stage_two_model):
    """Stop at the first confident route; never retry a failed stage."""
    stage_one = assess_stage_one(user_message, recent_turns)
    if stage_one["confident"] and _valid_context_selection(stage_one["selection"]):
        return stage_one["selection"]
    if stage_one["confident"]:
        stage_one = {**stage_one, "confident": False, "reason": "invalid_stage_one_result"}

    try:
        stage_two = classify_agent_intent(
            client, user_message, recent_turns, stage_two_model,
        )
        if stage_two.confidence == "high":
            return context_from_classification(stage_two)
        stage_two_result = {
            "classification": stage_two.model_dump(),
            "reason": "low_confidence",
        }
    except Exception:
        stage_two_result = {
            "classification": None,
            "reason": "invalid_or_unavailable",
        }

    try:
        decision = classify_stage_three(
            client, user_message, recent_turns, stage_one, stage_two_result,
        )
        return context_from_classification(decision)
    except Exception:
        return SAFE_MINIMAL_CONTEXT.copy()
