"""Coordinate routing, fresh observations and main-agent reasoning."""

import os
from copy import deepcopy

from openai import OpenAI

from backend.app.infrastructure.token_usage import token_usage_session

from backend.app.ai.config import (
    get_agent_model_settings,
    is_openai_api_key_configured,
    get_max_recent_turns,
)
from backend.app.ai.agent import reasoning
from backend.app.ai.agent.coverage import exam_context_coverage, add_exam_coverage_notice
from backend.app.ai.context.selection import select_agent_context
from backend.app.ai.context.policy import apply_context_exclusions, excluded_context_sources
from backend.app.ai.context.exam_policy import choose_exam_filter
from backend.app.ai.context.activity_targets import requested_activity_ids
from backend.app.ai.observations.activities import build_activity_observation
from backend.app.ai.observations.collect import collect_agent_observations
from backend.app.ai.observations.exams import build_exam_observation
from backend.app.ai.observations.memory import build_memory_observation
from backend.app.ai.observations.proposal_schedule import build_proposal_schedule_observation
from backend.app.ai.agent.followup import prepare_followup, validate_followup
from backend.app.ai.agent.transparency import build_proposal_context, record_routing_outcome
from backend.app.ai.agent.context_recovery import (
    MAX_CONTEXT_RECOVERY_RETRIES, build_context_status, read_observation,
)


PROPOSAL_MODEL = "gpt-6-luna"


def get_agent_proposal(
    connection, user_request, recent_turns=None, *, session_id=None,
    include_context=False, memory_reader=None, chat_summary=None,
    routing_evidence=None, adaptive_snapshot=None, file_reader=None, file_detector=None,
):
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
    file_reference = None
    if file_detector is not None and "files" not in excluded_sources:
        detection = read_observation(file_detector, user_request)
        if detection and detection.get("selection"):
            file_reference = detection

    def finish(proposal):
        coverage = exam_context_coverage(context.get("exams"))
        proposal = add_exam_coverage_notice(proposal, coverage)
        record_routing_outcome(
            routing_evidence, classifier_model=PROPOSAL_MODEL, selection=selection,
            initial_status=initial_status, context_status=context_status,
            excluded_sources=excluded_sources, target_ids=target_ids, recent_turns=recent_turns,
            user_request=user_request, recovery_trace=recovery_trace, memory_requested=memory_requested,
        )
        if not include_context:
            return proposal
        return {**proposal, "agent_context": build_proposal_context(
            routing_trace=routing_trace, selection=selection,
            recent_count=len(list(recent_turns or [])[-get_max_recent_turns():]),
            lookups=lookups, context=context, coverage=coverage, chat_summary=chat_summary,
            initial_status=initial_status, context_status=context_status, recovery_trace=recovery_trace,
            excluded_sources=excluded_sources, model=agent_settings["model"], routing_evidence=routing_evidence,
            adaptive_snapshot=adaptive_snapshot, token_usage=usage_stats.snapshot(),
            file_reference=file_reference, target_ids=target_ids,
        )}

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

    def ask(client, remaining, feedback=None):
        recovery_trace["main_agent_attempts"] += 1
        response = reasoning.request_agent_response(
            client, user_request, context, recent_turns, agent_settings, output_limit,
            context_status=context_status, context_recovery_remaining=remaining,
            **({"context_recovery_feedback": feedback} if feedback else {}),
            **({"chat_summary": chat_summary} if chat_summary is not None else {}),
        )
        return reasoning.parse_agent_response(response)

    def read_memory(selected):
        if memory_reader is not None:
            return memory_reader(selected)
        return build_memory_observation(selected, session_id=session_id)

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
        proposal = ask(client, MAX_CONTEXT_RECOVERY_RETRIES)
        memory_requested = proposal.get("memory_request") is not None
        followup = prepare_followup(
            proposal, context=context, context_status=context_status, selection=selection,
            session_id=session_id, excluded_sources=excluded_sources, trace=recovery_trace,
            lookups=lookups, include_context=include_context, collect=collect,
            read_schedule=lambda dates: read_observation(build_proposal_schedule_observation, connection, dates),
            read_memory=read_memory,
        )
        if followup is None:
            return finish(proposal)
        context_status = build_context_status(context, memory_available=session_id is not None)
        if followup.clarification is not None:
            return finish(followup.clarification)

        # Schedule checks, missing observations and historical lookup share this
        # single second call. Validation can only return an answer or clarify.
        proposal = validate_followup(ask(client, 0, followup.feedback), context, recovery_trace)
    return finish(proposal)
