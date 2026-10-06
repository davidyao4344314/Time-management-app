"""Generic owner-scoped confirmation API; only explicit decisions execute."""

import os
from sqlite3 import Error as SQLiteError
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api import action_runtime
from backend.app.api.conversations import resolve_owner
from backend.app.ai.actions.contracts import ApprovalDecision
from backend.app.ai.actions.service import ProposalConflict, ProposalNotFound
from backend.app.dev.action_proposals import create_test_activity_proposal

router = APIRouter(prefix="/actions")


class ActionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["confirm", "cancel"]


class TestProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _dev_enabled():
    # Explicit process opt-in; do not modify/read keys or enable this by default.
    return os.getenv("ACTION_LAYER_DEV_MODE") == "1"


def _call(request, response, function, *args):
    try:
        response.headers["Cache-Control"] = "no-store"
        owner = resolve_owner(request, response)
        return function(owner, *args)
    except ProposalNotFound:
        raise HTTPException(404, "Action proposal not found.") from None
    except ProposalConflict as error:
        raise HTTPException(409, str(error)) from None
    except (SQLiteError, OSError):
        raise HTTPException(503, "Could not access local action storage. Refresh the proposal status.") from None


@router.get("/proposals")
def list_proposals(request: Request, response: Response):
    return {"proposals": _call(request, response, action_runtime.service.list_proposals), "dev_enabled": _dev_enabled()}


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request, response: Response):
    return _call(request, response, action_runtime.service.get_proposal, proposal_id)


@router.post("/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, body: ActionDecisionRequest, request: Request, response: Response):
    decision = ApprovalDecision.APPROVE if body.decision == "confirm" else ApprovalDecision.REJECT
    return _call(request, response, action_runtime.service.decide, proposal_id, decision)


@router.post("/dev/proposals", status_code=201)
def create_test_proposal(body: TestProposalRequest, request: Request, response: Response):
    if not _dev_enabled():
        raise HTTPException(404, "The action proposal test path is disabled.")
    return _call(request, response, action_runtime.service.register, create_test_activity_proposal())
