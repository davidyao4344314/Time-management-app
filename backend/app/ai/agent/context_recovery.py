"""Small context manifests and validation; no queries or agent retry loop."""

import sqlite3

from backend.app.ai.agent.contracts import MissingContextRequest
from backend.app.ai.context.contracts import ContextSelection


MAX_CONTEXT_RECOVERY_RETRIES = 1
ALLOWED_MISSING_CONTEXT_SOURCES = frozenset({"activities", "exams"})


def read_observation(builder, *args, **kwargs):
    """Keep a failed read distinct from a successful query with no records."""
    try:
        return builder(*args, **kwargs)
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        return {"status": "unavailable"}


def observation_status(source, observation):
    if not isinstance(observation, dict):
        return "unavailable"
    if observation.get("status") == "unavailable":
        return "unavailable"
    if source == "memory":
        if observation.get("items"):
            return "provided"
        return "empty" if observation.get("status") == "empty" else "unavailable"
    # Full counts remain authoritative when the detailed list is truncated.
    if type(observation.get("count")) is int:
        if observation["count"] < 0:
            return "unavailable"
        return "provided" if observation["count"] > 0 else "empty"
    fields = ("current", "today", "all_activities", "upcoming_7d", "upcoming_month") \
        if source == "activities" else ("upcoming",)
    lists = [observation[field] for field in fields if isinstance(observation.get(field), list)]
    if any(lists) or observation.get("next") or observation.get("busy") or observation.get("truncated"):
        return "provided"
    return "empty" if lists else "unavailable"


def build_context_status(observations, *, memory_available=False):
    """The current request and bounded recent chat are always sent separately."""
    result = {"current_chat": "provided"}
    for source in ("activities", "exams"):
        result[source] = observation_status(source, observations[source]) \
            if source in observations else "not_selected"
    memory = observations.get("memory")
    if memory is not None and memory.get("scope") != "current_chat":
        result["global_memory"] = observation_status("memory", memory)
    else:
        result["global_memory"] = "not_selected" if memory_available else "unavailable"
    return result


def recovery_selection(requests, context_status, *, excluded_sources=()):
    """Validate against current source status before any observation is read."""
    if not isinstance(requests, list) or not 1 <= len(requests) <= 2:
        raise ValueError("Request one or two missing observations.")
    selection = {"activities_scope": None, "include_exams": False, "exam_scope": None}
    seen = set()
    for value in requests:
        request = MissingContextRequest.model_validate(value)
        if request.source not in ALLOWED_MISSING_CONTEXT_SOURCES or request.source in seen:
            raise ValueError("The observation source is unsupported or duplicated.")
        if request.source in excluded_sources:
            raise ValueError("The user excluded this observation source.")
        if context_status.get(request.source) != "not_selected":
            raise ValueError("Only unselected observations can be recovered.")
        seen.add(request.source)
        if request.source == "activities":
            selection["activities_scope"] = request.time_scope
        else:
            selection.update(include_exams=True, exam_scope=request.time_scope)
    ContextSelection.model_validate(selection)
    return selection
