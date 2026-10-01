"""Coordinate routing, fresh observations and main-agent reasoning."""

import os

from openai import OpenAI

from backend.app.ai.config import (
    get_agent_model_settings,
    is_openai_api_key_configured,
    get_max_recent_turns,
)
from backend.app.ai.agent import reasoning
from backend.app.ai.context.selection import select_agent_context
from backend.app.ai.observations.activities import build_activity_observation
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.observations.memory import build_memory_observation
from backend.app.ai.memory.contracts import MemorySelection
from backend.app.ai.agent.transparency import build_agent_context


PROPOSAL_MODEL = "gpt-6-luna"


def get_agent_proposal(connection, user_request, recent_turns=None, *, session_id=None, include_context=False):
    """Return a validated message and proposed actions; never write to SQLite."""
    if not is_openai_api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("A user request is required.")

    agent_settings = get_agent_model_settings()
    output_limit, timeout = reasoning.proposal_request_limits(
        agent_settings["reasoning_effort"],
    )
    routing_trace = {}
    lookups = []

    def finish(proposal):
        if not include_context:
            return proposal
        recent_count = len(list(recent_turns or [])[-get_max_recent_turns():])
        return {**proposal, "agent_context": build_agent_context(
            routing_trace, selection, recent_count, lookups,
        )}

    with OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=timeout, max_retries=0) as client:
        selection = select_agent_context(
            client, user_request.strip(), recent_turns, PROPOSAL_MODEL,
            **({"trace": routing_trace} if include_context else {}),
        )
        context = collect_agent_observations(
            connection, selection,
            activity_builder=build_activity_observation,
            exam_builder=build_exam_observation,
            session_id=session_id,
        )
        if include_context and selection.get("memory") is not None:
            lookups.append({"phase": "initial", "sources": selection["memory"]["sources"],
                            "result": context["memory"], "used_in_model": True})
        response = reasoning.request_agent_response(
            client, user_request, context, recent_turns, agent_settings, output_limit,
        )
        proposal = reasoning.parse_agent_response(response)
        request = proposal.get("memory_request")
        if request is not None and session_id is not None:
            # One extra read-only lookup at most. No intermediate turn is saved.
            memory_selection = MemorySelection.model_validate({
                "sources": ["raw_archive", "compressed_archive", "durable"],
                "query": request,
            }).model_dump()
            old_query = (selection.get("memory") or {}).get("query")
            if old_query == request:
                return finish(_memory_clarification())
            memory = build_memory_observation(memory_selection, session_id=session_id)
            lookup = {"phase": "followup", "sources": memory_selection["sources"],
                      "result": memory, "used_in_model": False}
            if include_context:
                lookups.append(lookup)
            if not memory["items"] or memory["items"] == context.get("memory", {}).get("items"):
                return finish(_memory_clarification())
            context["memory"] = {**memory, "followup_lookup_remaining": 0}
            lookup["used_in_model"] = True
            response = reasoning.request_agent_response(
                client, user_request, context, recent_turns, agent_settings, output_limit,
            )
            proposal = reasoning.parse_agent_response(response)
            if proposal.get("memory_request") is not None:
                return finish(_memory_clarification())
    return finish(proposal)


def _memory_clarification():
    return {"message": "I couldn't retrieve enough reliable historical context. Could you remind me of the discussion or give a more specific topic?",
            "actions": [], "memory_request": None}
