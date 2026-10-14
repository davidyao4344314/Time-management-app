"""Small context manifests and validation; no queries or agent retry loop."""

import sqlite3
from datetime import date, timedelta

from backend.app.ai.agent.contracts import MissingContextRequest, MissingFileContextRequest
from backend.app.ai.context.contracts import ContextSelection
from backend.app.ai.observations.formatting import observation_date_range, UPCOMING_LOOKAHEAD_DAYS
from backend.app.infrastructure.clock import local_now


MAX_CONTEXT_RECOVERY_RETRIES = 1
ALLOWED_MISSING_CONTEXT_SOURCES = frozenset({"activities", "exams", "files"})


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
    if source == 'activities' and observation.get('requested_activity_count', 0) > 0:
        return 'provided'
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
    for source in ("activities", "exams", "files"):
        result[source] = observation_status(source, observations[source]) \
            if source in observations else "not_selected"
    memory = observations.get("memory")
    if memory is not None and memory.get("scope") != "current_chat":
        result["global_memory"] = observation_status("memory", memory)
    else:
        result["global_memory"] = "not_selected" if memory_available else "unavailable"
    return result


def _scope_period(scope, today):
    if scope == "all":
        # Definitions are useful for targeting an ID, but not availability.
        return None
    first, last = ((today, today + timedelta(days=UPCOMING_LOOKAHEAD_DAYS))
                   if scope == "upcoming" else observation_date_range(today, scope))
    return max(first, today), last


def _needs_new_window(request, current_selection, observations, today):
    old_scope = current_selection.get(
        "activities_scope" if request.source == "activities" else "exam_scope",
    )
    if old_scope is None:
        # Missing provenance is not permission to refetch an already-read source.
        return False
    if request.time_scope == "all" or old_scope == "all":
        return request.time_scope != old_scope
    requested = _scope_period(request.time_scope, today)
    period = observations.get(request.source, {}).get("period", {})
    try:
        existing = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        if existing[0] > existing[1]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        existing = _scope_period(old_scope, today)
    return not (existing[0] <= requested[0] and requested[1] <= existing[1])


def build_recovery_plan(requests, context_status, *, excluded_sources=(),
                        current_selection=None, observations=None):
    """Separate permitted reads from already-covered schedule requests.

    A provided/empty schedule describes one window, not every possible date.
    Another window may be read within the same single retry budget. Redundant
    schedule requests reuse existing data with explicit feedback, without a read.
    Excluded/unavailable sources and already-selected files remain guarded.
    """
    if not isinstance(requests, list) or not 1 <= len(requests) <= 2:
        raise ValueError("Request one or two missing observations.")
    selection = {"activities_scope": None, "include_exams": False, "exam_scope": None}
    fetch_requests, already_available = [], []
    today = local_now().date()
    seen = set()
    for value in requests:
        if not isinstance(value, dict):
            raise ValueError("A missing-context request must be an object.")
        request = (MissingFileContextRequest.model_validate(value) if value.get("source") == "files"
                   else MissingContextRequest.model_validate(value))
        if request.source not in ALLOWED_MISSING_CONTEXT_SOURCES or request.source in seen:
            raise ValueError("The observation source is unsupported or duplicated.")
        if request.source in excluded_sources:
            raise ValueError("The user excluded this observation source.")
        status = context_status.get(request.source)
        if request.source != "files" and status in {"provided", "empty"}:
            if not _needs_new_window(request, current_selection or {}, observations or {}, today):
                already_available.append(request.model_dump())
                seen.add(request.source)
                continue
        elif status != "not_selected":
            raise ValueError("Only unselected observations can be recovered.")
        seen.add(request.source)
        fetch_requests.append(request.model_dump())
        if request.source == "activities":
            selection["activities_scope"] = request.time_scope
        elif request.source == "exams":
            selection.update(include_exams=True, exam_scope=request.time_scope)
        else:
            selection["files"] = {"query": request.query}
    ContextSelection.model_validate(selection)
    return {"selection": selection, "fetch_requests": fetch_requests,
            "already_available": already_available}


def recovery_selection(requests, context_status, *, excluded_sources=()):
    """Compatibility selector for callers without window/observation provenance."""
    plan = build_recovery_plan(requests, context_status, excluded_sources=excluded_sources)
    if plan["already_available"]:
        raise ValueError("Only unselected observations can be recovered.")
    return plan["selection"]
