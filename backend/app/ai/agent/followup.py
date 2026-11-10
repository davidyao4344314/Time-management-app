"""Prepare at most one read-only follow-up; no model calls or action execution."""

from dataclasses import dataclass

from backend.app.ai.agent.context_recovery import (
    build_context_status, build_recovery_plan, observation_status,
)
from backend.app.ai.agent.schedule_guard import proposal_schedule_dates, unchecked_proposal_dates
from backend.app.ai.context.policy import memory_selection_allowed
from backend.app.ai.memory.contracts import MemorySelection


@dataclass
class Followup:
    feedback: list | None = None
    clarification: dict | None = None


def prepare_followup(proposal, *, context, context_status, selection, session_id,
                     excluded_sources, trace, lookups, include_context,
                     collect, read_schedule, read_memory):
    """Return None, a clarification, or the inputs needed for one more call.

    Context, selection, and traces are request-local and updated in place.
    The caller owns the model call and the follow-up budget.
    """
    request = proposal.get("memory_request")
    missing = proposal.get("missing_context", [])
    schedule_dates = unchecked_proposal_dates(proposal, context)
    if not missing and not schedule_dates and not (request is not None and session_id is not None):
        return None

    recovered = False
    recovery_feedback = []
    if schedule_dates:
        # Recheck the whole draft, not just uncovered dates: replacing a
        # broad observation must not discard coverage for other batch items.
        schedule_dates = proposal_schedule_dates(proposal)
        if "activities" in excluded_sources:
            return Followup(clarification=_schedule_clarification("May I check your calendar before proposing study times? You excluded calendar access for this request."))
        if context_status["activities"] == "unavailable":
            return Followup(clarification=_schedule_clarification("I couldn't read your current calendar. Please try again before I propose study times."))
        schedule = read_schedule(schedule_dates)
        before = context_status["activities"]
        context["activities"] = schedule
        context_status = build_context_status(context, memory_available=session_id is not None)
        trace["attempts"] = 1
        trace["requests"].append({"source": "activities", "time_scope": "proposed_dates",
            "dates": [day.isoformat() for day in schedule_dates],
            "status_before": before, "status_after": context_status["activities"]})
        if context_status["activities"] == "unavailable":
            trace["status"] = "unavailable"
            return Followup(clarification=_schedule_clarification("I couldn't verify your proposed study dates against the current calendar. Please try again."))
        recovered = True
        trace["status"] = "fetched"
        recovery_feedback = [{"source": "activities", "reason": "Review the draft using fresh busy intervals for checked_dates; the draft was not saved."}]
    if missing:
        try:
            plan = build_recovery_plan(
                missing, context_status, excluded_sources=excluded_sources,
                current_selection=selection, observations=context,
            )
        except ValueError:
            trace["status"] = "rejected"
            return Followup(clarification=_context_clarification())
        trace["attempts"] = 1
        selected = plan["selection"]
        recovery_feedback = plan["already_available"]
        # A harmless redundant request gets the same one-shot correction,
        # using the supplied observations instead of discarding them.
        for item in recovery_feedback:
            source = item["source"]
            trace["requests"].append({**item,
                "status_before": context_status[source], "status_after": context_status[source],
                "resolution": "already_available"})
        recovered = bool(recovery_feedback)
        extra = collect(selected) if plan["fetch_requests"] else {}
        for item in plan["fetch_requests"]:
            source = item["source"]
            status = observation_status(source, extra.get(source))
            trace["requests"].append({**item,
                "status_before": context_status[source], "status_after": status})
            context[source] = extra.get(source, {"status": "unavailable"})
            recovered |= status != "unavailable"
        if selected["activities_scope"] is not None:
            selection["activities_scope"] = selected["activities_scope"]
        if selected["include_exams"]:
            selection.update(include_exams=True, exam_scope=selected["exam_scope"])
        if selected.get("files") is not None:
            selection["files"] = selected["files"]
        trace["status"] = "fetched" if recovered else "unavailable"

    if request is not None and session_id is not None:
        memory_selection = MemorySelection.model_validate({
            "sources": ["raw_archive", "compressed_archive", "durable"],
            "query": request,
            # A follow-up lookup must retain an explicitly local scope.
            **({"scope": selection["memory"]["scope"]}
               if (selection.get("memory") or {}).get("scope") else {}),
        }).model_dump()
        if not memory_selection_allowed(memory_selection, excluded_sources):
            trace['status'] = 'rejected'
            return Followup(clarification=_memory_clarification())
        old_query = (selection.get("memory") or {}).get("query")
        old_sources = (selection.get('memory') or {}).get('sources', [])
        already_searched = old_query == request and set(memory_selection['sources']) <= set(old_sources)
        if not already_searched:
            memory = read_memory(memory_selection)
            lookup = {"phase": "followup", "sources": memory_selection["sources"],
                      "result": memory, "used_in_model": False}
            if include_context:
                lookups.append(lookup)
            if memory["items"] and memory["items"] != context.get("memory", {}).get("items"):
                context["memory"] = {**memory, "followup_lookup_remaining": 0}
                lookup["used_in_model"] = True
                recovered = True
            elif "memory" not in context:
                # A successful schedule recovery can still retry with an
                # empty/unavailable historical result. Keep earlier useful
                # memory intact when a different follow-up query has no match.
                context["memory"] = {**memory, "followup_lookup_remaining": 0}
                lookup["used_in_model"] = recovered
        if not recovered:
            return Followup(clarification=_memory_clarification())

    if not recovered:
        return Followup(clarification=_context_clarification())

    if "memory" in context:
        context["memory"] = {**context["memory"], "followup_lookup_remaining": 0}
    return Followup(feedback=recovery_feedback)


def validate_followup(proposal, context, trace):
    """Return the checked second answer or a clarification; never try again."""
    if proposal.get("missing_context"):
        trace["status"] = "exhausted"
        return _context_clarification()
    if proposal.get("memory_request") is not None:
        trace["status"] = "exhausted"
        return _memory_clarification()
    if unchecked_proposal_dates(proposal, context):
        trace["status"] = "exhausted"
        return _schedule_clarification("The new proposed dates are outside the calendar dates checked in this request. Which dates should the study sessions use?")
    trace["status"] = "completed"
    return proposal


def _context_clarification():
    return {"message": "I couldn't obtain enough reliable context to answer. Could you clarify what information I should base the answer on?",
            "actions": [], "memory_request": None, "missing_context": []}


def _memory_clarification():
    return {"message": "I couldn't retrieve enough reliable historical context. Could you remind me of the discussion or give a more specific topic?",
            "actions": [], "memory_request": None, "missing_context": []}


def _schedule_clarification(message):
    return {"message": message, "actions": [], "memory_request": None, "missing_context": []}
