"""Coordinate routing, fresh observations and main-agent reasoning."""

import os
import re
from backend.app.infrastructure.token_usage import token_usage_session
from copy import deepcopy

from openai import OpenAI

from backend.app.ai.config import (
    get_agent_model_settings,
    is_openai_api_key_configured,
    get_max_recent_turns,
)
from backend.app.ai.agent import reasoning
from backend.app.ai.agent.coverage import exam_context_coverage, add_exam_coverage_notice
from backend.app.ai.context.selection import select_agent_context
from backend.app.ai.context.policy import apply_context_exclusions, excluded_context_sources, memory_selection_allowed
from backend.app.ai.context.exam_policy import choose_exam_filter
from backend.app.ai.context.activity_targets import requested_activity_ids
from backend.app.ai.observations.activities import build_activity_observation
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.observations.memory import build_memory_observation
from backend.app.ai.observations.proposal_schedule import build_proposal_schedule_observation
from backend.app.ai.agent.schedule_guard import unchecked_proposal_dates, proposal_schedule_dates
from backend.app.ai.memory.contracts import MemorySelection
from backend.app.ai.agent.transparency import build_agent_context, build_adaptive_metadata
from backend.app.ai.agent.context_recovery import (
    MAX_CONTEXT_RECOVERY_RETRIES, build_context_status, read_observation,
    build_recovery_plan, observation_status,
)


PROPOSAL_MODEL = "gpt-6-luna"


def get_agent_proposal(connection, user_request, recent_turns=None, *, session_id=None, include_context=False, memory_reader=None, chat_summary=None, routing_evidence=None, adaptive_snapshot=None, file_reader=None, file_detector=None):
    """Return a validated message and proposed actions; never write to SQLite."""
    if not is_openai_api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("A user request is required.")

    excluded_sources = excluded_context_sources(user_request)
    exam_filter = choose_exam_filter(user_request, recent_turns)
    target_ids = requested_activity_ids(user_request) if 'activities' not in excluded_sources else []

    agent_settings = get_agent_model_settings()
    output_limit, timeout = reasoning.proposal_request_limits(
        agent_settings["reasoning_effort"],
    )
    routing_trace = {}
    lookups = []
    recovery_trace = {"max_retries": MAX_CONTEXT_RECOVERY_RETRIES, "attempts": 0,
                      "main_agent_attempts": 0, "status": "not_requested", "requests": []}
    followup_count = 0
    memory_requested = False
    file_reference = None
    if file_detector is not None and "files" not in excluded_sources:
        detection = read_observation(file_detector, user_request)
        if detection and detection.get("selection"):
            file_reference = detection

    def finish(proposal):
        coverage = exam_context_coverage(context.get("exams"))
        proposal = add_exam_coverage_notice(proposal, coverage)
        if routing_evidence is not None:
            routing_evidence.update(
                classifier_model=PROPOSAL_MODEL,
                final_selection=deepcopy(selection), initial_status=initial_status, final_status=context_status,
                excluded_sources=sorted(excluded_sources),
                context_dependent=bool(target_ids or selection.get("files") or (recent_turns and re.search(r"\b(it|that|those|same|earlier|previously)\b", user_request.casefold()))),
                recovery_requested=bool(recovery_trace["attempts"] or memory_requested),
                recovery_completed=recovery_trace["status"] == "completed",
            )
        if not include_context:
            return proposal
        recent_count = len(list(recent_turns or [])[-get_max_recent_turns():])
        public = build_agent_context(
            routing_trace, selection, recent_count, lookups,
        )
        checked_dates = context.get("activities", {}).get("checked_dates")
        if checked_dates:
            for source in public["context_sources"]:
                if source["source"] == "activities":
                    source.update(selected=True, reason="Fresh calendar check for proposed dates: " + ", ".join(checked_dates))
        if coverage is not None:
            public["exam_coverage"] = coverage
            for source in public["context_sources"]:
                if source["source"] == "exams" and source["selected"]:
                    source["reason"] += " " + coverage["notice"]
        if chat_summary:
            public['context_sources'].append({'source':'chat_summary','label':'Current-chat summary',
                'selected':True,'authority':'historical_summary','reason':'Bounded summary of older completed messages in this chat.'})
        public.update(initial_context_status=initial_status, context_status=context_status,
                      context_recovery=recovery_trace, excluded_sources=sorted(excluded_sources),
                      model=agent_settings["model"],
                      adaptive_routing=build_adaptive_metadata(routing_evidence, adaptive_snapshot))
        public["token_usage"] = usage_stats.snapshot()
        file_observation = context.get("files", {})
        # Keep only references and counts in persisted inspector metadata. Never
        # copy extracted text/chunks into recent/archive/durable conversation memory.
        public["file_context"] = {
            "status": context_status["files"],
            "detection": file_reference["method"] if file_reference else "context_selection",
            "chunk_count": file_observation.get("count", 0),
            "truncated": bool(file_observation.get("truncated")),
            "ambiguous": bool(file_observation.get("ambiguous")),
            "reference_matched": bool(file_reference and file_reference["method"] != "unknown_filename"
                                      and file_observation.get("files")),
            "requested_filenames": file_reference.get("filenames", []) if file_reference else [],
            "resolved_file_ids": (selection.get("files") or {}).get("file_ids", []),
            "files": [{key: item.get(key) for key in ("file_id", "filename", "file_type", "created_at", "chunk_count")}
                      for item in file_observation.get("files", [])],
        }
        public["file_refs"] = ([item["file_id"] for item in file_observation.get("files", [])][:3]
                               if context_status["files"] == "provided" else [])
        if target_ids:
            public['activity_target_lookup'] = {'requested_ids': target_ids,
                'matched_count': context.get('activities', {}).get('requested_activity_count', 0)}
        return {**proposal, 'agent_context':public}

    def collect(selected):
        return collect_agent_observations(
            connection, selected,
            activity_builder=lambda *args, **kwargs: read_observation(build_activity_observation, *args, **kwargs),
            exam_builder=lambda *args, **kwargs: read_observation(build_exam_observation, *args, **kwargs),
            session_id=session_id,
            **({"exam_filter": exam_filter} if exam_filter != "all" else {}),
            **({'excluded_sources': excluded_sources} if excluded_sources else {}),
            **({'memory_builder': memory_reader} if memory_reader is not None else {}),
            **({'file_reader': file_reader} if file_reader is not None else {}),
            **({'activity_ids': target_ids} if target_ids else {}),
        )

    with token_usage_session(enabled=include_context) as usage_stats, \
            OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=timeout, max_retries=0) as client:
        selection = select_agent_context(
            client, user_request.strip(), recent_turns, PROPOSAL_MODEL,
            **({"trace": routing_trace} if include_context else {}),
            **({"evidence": routing_evidence} if routing_evidence is not None else {}),
            **({"adaptive_snapshot": adaptive_snapshot} if adaptive_snapshot is not None else {}),
            **({"file_reference": file_reference} if file_reference is not None else {}),
        )
        selection = apply_context_exclusions(selection, excluded_sources)
        if target_ids and selection['activities_scope'] is None:
            selection['activities_scope'] = 'all'
        if routing_evidence is not None:
            routing_evidence["initial_selection"] = deepcopy(selection)
        context = dict(collect(selection))
        context_status = build_context_status(context, memory_available=session_id is not None)
        initial_status = dict(context_status)
        if include_context and selection.get("memory") is not None:
            lookups.append({"phase": "initial", "sources": selection["memory"]["sources"],
                            "result": context["memory"], "used_in_model": True})
        recovery_trace["main_agent_attempts"] = 1
        response = reasoning.request_agent_response(
            client, user_request, context, recent_turns, agent_settings, output_limit,
            context_status=context_status, context_recovery_remaining=MAX_CONTEXT_RECOVERY_RETRIES,
            **({'chat_summary':chat_summary} if chat_summary is not None else {}),
        )
        proposal = reasoning.parse_agent_response(response)
        request = proposal.get("memory_request")
        memory_requested = request is not None
        missing = proposal.get("missing_context", [])
        schedule_dates = unchecked_proposal_dates(proposal, context)
        if not missing and not schedule_dates and not (request is not None and session_id is not None):
            return finish(proposal)

        # One shared follow-up budget covers schedule recovery and the existing
        # historical lookup. There is no retry loop or third main-agent call.
        if followup_count >= MAX_CONTEXT_RECOVERY_RETRIES:
            return finish(_context_clarification())
        recovered = False
        recovery_feedback = []
        if schedule_dates:
            # Recheck the whole draft, not just uncovered dates: replacing a
            # broad observation must not discard coverage for other batch items.
            schedule_dates = proposal_schedule_dates(proposal)
            if "activities" in excluded_sources:
                return finish(_schedule_clarification("May I check your calendar before proposing study times? You excluded calendar access for this request."))
            if context_status["activities"] == "unavailable":
                return finish(_schedule_clarification("I couldn't read your current calendar. Please try again before I propose study times."))
            schedule = read_observation(build_proposal_schedule_observation, connection, schedule_dates)
            before = context_status["activities"]
            context["activities"] = schedule
            context_status = build_context_status(context, memory_available=session_id is not None)
            recovery_trace["attempts"] = 1
            recovery_trace["requests"].append({"source": "activities", "time_scope": "proposed_dates",
                "dates": [day.isoformat() for day in schedule_dates],
                "status_before": before, "status_after": context_status["activities"]})
            if context_status["activities"] == "unavailable":
                recovery_trace["status"] = "unavailable"
                return finish(_schedule_clarification("I couldn't verify your proposed study dates against the current calendar. Please try again."))
            recovered = True
            recovery_trace["status"] = "fetched"
            recovery_feedback = [{"source": "activities", "reason": "Review the draft using fresh busy intervals for checked_dates; the draft was not saved."}]
        if missing:
            try:
                plan = build_recovery_plan(
                    missing, context_status, excluded_sources=excluded_sources,
                    current_selection=selection, observations=context,
                )
            except ValueError:
                recovery_trace["status"] = "rejected"
                return finish(_context_clarification())
            recovery_trace["attempts"] = 1
            selected = plan["selection"]
            recovery_feedback = plan["already_available"]
            # A harmless redundant request gets the same one-shot correction,
            # using the supplied observations instead of discarding them.
            for item in recovery_feedback:
                source = item["source"]
                recovery_trace["requests"].append({**item,
                    "status_before": context_status[source], "status_after": context_status[source],
                    "resolution": "already_available"})
            recovered = bool(recovery_feedback)
            extra = collect(selected) if plan["fetch_requests"] else {}
            for item in plan["fetch_requests"]:
                source = item["source"]
                status = observation_status(source, extra.get(source))
                recovery_trace["requests"].append({**item,
                    "status_before": context_status[source], "status_after": status})
                context[source] = extra.get(source, {"status": "unavailable"})
                recovered |= status != "unavailable"
            if selected["activities_scope"] is not None:
                selection["activities_scope"] = selected["activities_scope"]
            if selected["include_exams"]:
                selection.update(include_exams=True, exam_scope=selected["exam_scope"])
            if selected.get("files") is not None:
                selection["files"] = selected["files"]
            context_status = build_context_status(context, memory_available=session_id is not None)
            recovery_trace["status"] = "fetched" if recovered else "unavailable"

        if request is not None and session_id is not None:
            memory_selection = MemorySelection.model_validate({
                "sources": ["raw_archive", "compressed_archive", "durable"],
                "query": request,
                # A follow-up lookup must retain an explicitly local scope.
                **({"scope": selection["memory"]["scope"]}
                   if (selection.get("memory") or {}).get("scope") else {}),
            }).model_dump()
            if not memory_selection_allowed(memory_selection, excluded_sources):
                recovery_trace['status'] = 'rejected'
                return finish(_memory_clarification())
            old_query = (selection.get("memory") or {}).get("query")
            old_sources = (selection.get('memory') or {}).get('sources', [])
            already_searched = old_query == request and set(memory_selection['sources']) <= set(old_sources)
            if not already_searched:
                memory = (memory_reader(memory_selection) if memory_reader is not None
                          else build_memory_observation(memory_selection, session_id=session_id))
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
                context_status = build_context_status(context, memory_available=session_id is not None)
            if not recovered:
                return finish(_memory_clarification())

        if not recovered:
            return finish(_context_clarification())
        followup_count += 1
        if "memory" in context:
            context["memory"] = {**context["memory"], "followup_lookup_remaining": 0}
        context_status = build_context_status(context, memory_available=session_id is not None)
        recovery_trace["main_agent_attempts"] += 1
        response = reasoning.request_agent_response(
            client, user_request, context, recent_turns, agent_settings, output_limit,
            context_status=context_status,
            context_recovery_remaining=MAX_CONTEXT_RECOVERY_RETRIES - followup_count,
            **({'context_recovery_feedback': recovery_feedback} if recovery_feedback else {}),
            **({'chat_summary':chat_summary} if chat_summary is not None else {}),
        )
        proposal = reasoning.parse_agent_response(response)
        if proposal.get("missing_context"):
            recovery_trace["status"] = "exhausted"
            return finish(_context_clarification())
        if proposal.get("memory_request") is not None:
            recovery_trace["status"] = "exhausted"
            return finish(_memory_clarification())
        if unchecked_proposal_dates(proposal, context):
            recovery_trace["status"] = "exhausted"
            return finish(_schedule_clarification("The new proposed dates are outside the calendar dates checked in this request. Which dates should the study sessions use?"))
        recovery_trace["status"] = "completed"
    return finish(proposal)


def _context_clarification():
    return {"message": "I couldn't obtain enough reliable context to answer. Could you clarify what information I should base the answer on?",
            "actions": [], "memory_request": None, "missing_context": []}


def _memory_clarification():
    return {"message": "I couldn't retrieve enough reliable historical context. Could you remind me of the discussion or give a more specific topic?",
            "actions": [], "memory_request": None, "missing_context": []}


def _schedule_clarification(message):
    return {"message": message, "actions": [], "memory_request": None, "missing_context": []}
