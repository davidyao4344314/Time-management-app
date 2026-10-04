"""Coordinate routing, fresh observations and main-agent reasoning."""

import os
import re
from copy import deepcopy

from openai import OpenAI

from backend.app.ai.config import (
    get_agent_model_settings,
    is_openai_api_key_configured,
    get_max_recent_turns,
)
from backend.app.ai.agent import reasoning
from backend.app.ai.context.selection import select_agent_context
from backend.app.ai.context.policy import apply_context_exclusions, excluded_context_sources
from backend.app.ai.observations.activities import build_activity_observation
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.observations.memory import build_memory_observation
from backend.app.ai.memory.contracts import MemorySelection
from backend.app.ai.agent.transparency import build_agent_context
from backend.app.ai.agent.context_recovery import (
    MAX_CONTEXT_RECOVERY_RETRIES, build_context_status, read_observation,
    recovery_selection, observation_status,
)


PROPOSAL_MODEL = "gpt-6-luna"


def get_agent_proposal(connection, user_request, recent_turns=None, *, session_id=None, include_context=False, memory_reader=None, chat_summary=None, routing_evidence=None, adaptive_snapshot=None):
    """Return a validated message and proposed actions; never write to SQLite."""
    if not is_openai_api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("A user request is required.")

    excluded_sources = excluded_context_sources(user_request)

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

    def finish(proposal):
        if routing_evidence is not None:
            routing_evidence.update(
                classifier_model=PROPOSAL_MODEL,
                final_selection=deepcopy(selection), initial_status=initial_status, final_status=context_status,
                excluded_sources=sorted(excluded_sources),
                context_dependent=bool(recent_turns and re.search(r"\b(it|that|those|same|earlier|previously)\b", user_request.casefold())),
                recovery_requested=bool(recovery_trace["attempts"] or memory_requested),
                recovery_completed=recovery_trace["status"] == "completed",
            )
        if not include_context:
            return proposal
        recent_count = len(list(recent_turns or [])[-get_max_recent_turns():])
        public = build_agent_context(
            routing_trace, selection, recent_count, lookups,
        )
        if chat_summary:
            public['context_sources'].append({'source':'chat_summary','label':'Current-chat summary',
                'selected':True,'authority':'historical_summary','reason':'Bounded summary of older completed messages in this chat.'})
        public.update(initial_context_status=initial_status, context_status=context_status,
                      context_recovery=recovery_trace, excluded_sources=sorted(excluded_sources))
        return {**proposal, 'agent_context':public}

    def collect(selected):
        return collect_agent_observations(
            connection, selected,
            activity_builder=lambda *args, **kwargs: read_observation(build_activity_observation, *args, **kwargs),
            exam_builder=lambda *args, **kwargs: read_observation(build_exam_observation, *args, **kwargs),
            session_id=session_id,
            **({'excluded_sources': excluded_sources} if excluded_sources else {}),
            **({'memory_builder': memory_reader} if memory_reader is not None else {}),
        )

    with OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=timeout, max_retries=0) as client:
        selection = select_agent_context(
            client, user_request.strip(), recent_turns, PROPOSAL_MODEL,
            **({"trace": routing_trace} if include_context else {}),
            **({"evidence": routing_evidence} if routing_evidence is not None else {}),
            **({"adaptive_snapshot": adaptive_snapshot} if adaptive_snapshot is not None else {}),
        )
        selection = apply_context_exclusions(selection, excluded_sources)
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
        if not missing and not (request is not None and session_id is not None):
            return finish(proposal)

        # One shared follow-up budget covers schedule recovery and the existing
        # historical lookup. There is no retry loop or third main-agent call.
        if followup_count >= MAX_CONTEXT_RECOVERY_RETRIES:
            return finish(_context_clarification())
        recovered = False
        if missing:
            try:
                selected = recovery_selection(missing, context_status, excluded_sources=excluded_sources)
            except ValueError:
                recovery_trace["status"] = "rejected"
                return finish(_context_clarification())
            recovery_trace["attempts"] = 1
            extra = collect(selected)
            for item in missing:
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
            **({'chat_summary':chat_summary} if chat_summary is not None else {}),
        )
        proposal = reasoning.parse_agent_response(response)
        if proposal.get("missing_context"):
            recovery_trace["status"] = "exhausted"
            return finish(_context_clarification())
        if proposal.get("memory_request") is not None:
            recovery_trace["status"] = "exhausted"
            return finish(_memory_clarification())
        recovery_trace["status"] = "completed"
    return finish(proposal)


def _context_clarification():
    return {"message": "I couldn't obtain enough reliable context to answer. Could you clarify what information I should base the answer on?",
            "actions": [], "memory_request": None, "missing_context": []}


def _memory_clarification():
    return {"message": "I couldn't retrieve enough reliable historical context. Could you remind me of the discussion or give a more specific topic?",
            "actions": [], "memory_request": None, "missing_context": []}
