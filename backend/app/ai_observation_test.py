"""Send the existing compact observations to OpenAI for a receipt test only."""

import json
import os

from openai import OpenAI

from backend.app.activity_observation import build_activity_observation
from backend.app.ai_config import is_openai_api_key_configured
from backend.app.exam_observation import build_exam_observation


TEST_MODEL = "gpt-6-luna"


def send_observation_to_llm(connection):
    """Return True after OpenAI accepts both observations; discard its reply."""
    if not is_openai_api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    observation = {
        "activities": build_activity_observation(connection),
        "exams": build_exam_observation(connection),
    }

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip(), timeout=30, max_retries=0)
    response = client.responses.create(
        model=TEST_MODEL,
        instructions="You are receiving structured study-planning context. Confirm that the context was received.",
        input=json.dumps(observation, ensure_ascii=False, separators=(",", ":")),
        reasoning={"effort": "none"},
        max_output_tokens=64,
        store=False,
    )
    if response.status != "completed":
        raise RuntimeError("OpenAI did not complete the observation test.")
    return True
