"""Coordinate routing, fresh observations and main-agent reasoning."""

import os

from openai import OpenAI

from backend.app.ai_config import (
    get_agent_model_settings,
    is_openai_api_key_configured,
)
from backend.app.agent import reasoning
from backend.app.context.selection import select_agent_context
from backend.app.observations.activities import build_activity_observation
from backend.app.observations.collect import collect_agent_observations
from backend.app.observations.exams import build_exam_observation


PROPOSAL_MODEL = "gpt-6-luna"


def get_agent_proposal(connection, user_request, recent_turns=None):
    """Return a validated message and proposed actions; never write to SQLite."""
    if not is_openai_api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("A user request is required.")

    agent_settings = get_agent_model_settings()
    output_limit, timeout = reasoning.proposal_request_limits(
        agent_settings["reasoning_effort"],
    )
    with OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=timeout, max_retries=0) as client:
        selection = select_agent_context(
            client, user_request.strip(), recent_turns, PROPOSAL_MODEL,
        )
        context = collect_agent_observations(
            connection, selection,
            activity_builder=build_activity_observation,
            exam_builder=build_exam_observation,
        )
        response = reasoning.request_agent_response(
            client, user_request, context, recent_turns, agent_settings, output_limit,
        )
    return reasoning.parse_agent_response(response)
