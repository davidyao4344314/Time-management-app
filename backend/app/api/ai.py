"""AI configuration and proposal HTTP endpoints; no activity execution."""

import sqlite3
from uuid import uuid4
from sqlite3 import Error as SQLiteError

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from openai import OpenAIError
from pydantic import BaseModel, SecretStr, StrictInt, ValidationError

from backend.app.database import db_file
from backend.app.ai.config import (
    AGENT_MODEL_OPTIONS,
    MAX_RECENT_TURNS,
    MIN_RECENT_TURNS,
    get_agent_model_settings,
    get_max_recent_turns,
    is_openai_api_key_configured,
    save_agent_model_settings,
    save_max_recent_turns,
    save_openai_api_key,
)
from backend.app.ai.memory.recent import add_completed_turn, get_recent_turns, has_session
from backend.app.dev.observation_smoke import send_observation_to_llm
from backend.app.ai.agent.contracts import InvalidProposalError
from backend.app.ai.agent.service import get_agent_proposal

router = APIRouter()


class AIConfigRequest(BaseModel):
    api_key: SecretStr


@router.get("/ai/config/status")
def ai_config_status():
    return {"configured": is_openai_api_key_configured()}


@router.post("/ai/config")
def configure_ai(config_request: AIConfigRequest):
    try:
        save_openai_api_key(config_request.api_key.get_secret_value())
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter a valid API key without spaces.") from None
    except RuntimeError:
        raise HTTPException(
            status_code=500,
            detail="Could not save the API key locally. Check file permissions.",
        ) from None
    return {"configured": True}


class AIModelConfigRequest(BaseModel):
    model: str
    reasoning_effort: str


@router.get("/ai/model-config")
def ai_model_config():
    return {
        **get_agent_model_settings(),
        "models": [
            {"id": model, "efforts": efforts}
            for model, efforts in AGENT_MODEL_OPTIONS.items()
        ],
    }


@router.put("/ai/model-config")
def configure_ai_model(config_request: AIModelConfigRequest):
    try:
        return save_agent_model_settings(config_request.model, config_request.reasoning_effort)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Could not save model settings locally.") from None


class AIMemoryConfigRequest(BaseModel):
    max_recent_turns: StrictInt


@router.get("/ai/memory-config")
def ai_memory_config():
    return {
        "max_recent_turns": get_max_recent_turns(),
        "min": MIN_RECENT_TURNS,
        "max": MAX_RECENT_TURNS,
    }


@router.put("/ai/memory-config")
def configure_ai_memory(config_request: AIMemoryConfigRequest):
    try:
        return save_max_recent_turns(config_request.max_recent_turns)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Could not save the conversation limit locally.") from None


@router.post("/ai/test-observation")
def test_ai_observation():
    if not is_openai_api_key_configured():
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Configure OPENAI_API_KEY first."},
        )

    try:
        # This test must not modify SQLite, even if a migration is pending.
        connection = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
        try:
            send_observation_to_llm(connection)
        finally:
            connection.close()
    except SQLiteError:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Could not read the observation data."},
        )
    except OpenAIError:
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": "OpenAI request failed. Check the key, model access, and network."},
        )
    except RuntimeError:
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": "OpenAI did not complete the observation test."},
        )

    return {"success": True}


class AIProposalRequest(BaseModel):
    message: str


@router.post("/ai/propose")
def propose_ai(proposal_request: AIProposalRequest, request: Request, response: Response):
    user_message = proposal_request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Enter a request first.")
    if not is_openai_api_key_configured():
        raise HTTPException(status_code=400, detail="Configure OPENAI_API_KEY first.")

    session_id = request.cookies.get("ai_agent_session")
    new_session = not has_session(session_id)
    if new_session:
        session_id = uuid4().hex
    recent_turns = get_recent_turns(session_id)

    try:
        # Read-only: the proposed add_activity action is never executed here.
        connection = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
        try:
            proposal = get_agent_proposal(connection, user_message, recent_turns)
        finally:
            connection.close()
    except SQLiteError:
        raise HTTPException(status_code=500, detail="Could not read the observation data.") from None
    except OpenAIError:
        raise HTTPException(status_code=502, detail="OpenAI request failed. Check the key, model access, and network.") from None
    except (InvalidProposalError, ValidationError):
        raise HTTPException(status_code=502, detail="OpenAI did not return a valid proposal.") from None

    add_completed_turn(session_id, user_message, proposal)
    if new_session:
        response.set_cookie(
            key="ai_agent_session", value=session_id, httponly=True,
            samesite="lax", path="/", secure=request.url.scheme == "https",
        )
    return proposal
