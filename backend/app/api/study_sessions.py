"""Completion tracking uses the same local shared scope as planner activities."""

from contextlib import closing
from datetime import date
from sqlite3 import Error as SQLiteError
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.app.database import create_connection
from backend.app.planner import study_sessions

router = APIRouter(prefix='/study-sessions')


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['done', 'partly_done', 'missed']
    actual_minutes: StrictInt = Field(ge=0, le=1440)


def call_service(function, *args):
    try:
        with closing(create_connection()) as connection:
            return function(connection, *args)
    except study_sessions.SessionNotFoundError as error:
        raise HTTPException(404, str(error)) from None
    except study_sessions.SessionValidationError as error:
        raise HTTPException(400, str(error)) from None
    except SQLiteError:
        raise HTTPException(500, 'Could not access study session records. Please try again.') from None


@router.get('')
def list_sessions(response: Response, session_date: date | None = None):
    response.headers['Cache-Control'] = 'no-store'
    return call_service(study_sessions.list_sessions, session_date)


@router.put('/{activity_id}/{session_date}')
def save_session(activity_id: int, session_date: date, body: CompletionRequest):
    return call_service(study_sessions.save_session, activity_id, session_date, body.status, body.actual_minutes)


@router.delete('/{activity_id}/{session_date}', status_code=204)
def clear_session(activity_id: int, session_date: date):
    call_service(study_sessions.clear_session, activity_id, session_date)
    return Response(status_code=204)
