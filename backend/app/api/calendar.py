"""Calendar HTTP endpoints; business logic stays in backend services."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api import common
from datetime import date, timedelta
from backend.app.planner.activities import move_activity
from backend.app.planner.calendar import (
    check_activity_current, get_current_and_next_activities, get_current_time,
    get_todays_activities, get_week_activities, get_current_week,
    get_calendar_week,
)
from backend.app.planner.exams import get_all_exams

router = APIRouter()


class MoveActivityRequest(BaseModel):
    activity_id: int
    activity_type: str
    destination_date: str
    destination_weekday: str


@router.get("/activities/today")
def todays_activities():
    connection = common.create_connection()

    activities = get_todays_activities(connection)

    connection.close()

    return [common.activity_to_dict(activity) for activity in activities]


@router.get("/activities/current-next")
def current_and_next_activities():
    connection = common.create_connection()
    try:
        current, next_activity = get_current_and_next_activities(connection)
        return {
            "current": [common.activity_to_dict(activity) for activity in current] or None,
            "next": common.activity_to_dict(next_activity) if next_activity is not None else None,
        }
    finally:
        connection.close()


@router.get("/activities/current")
def current_activities():
    connection = common.create_connection()

    activities_today = get_todays_activities(connection)
    current_time = get_current_time()
    current_activity_ids = check_activity_current(
        activities_today,
        current_time,
    )

    activities_current = [
        activity
        for activity in activities_today
        if activity[0] in current_activity_ids
    ]

    connection.close()

    return [common.activity_to_dict(activity) for activity in activities_current]


@router.get("/activities/week")
def weekly_activities(week_start: date | None = None, include_exams: bool = False):
    if week_start is not None and week_start > date(9999, 12, 25):
        raise HTTPException(status_code=400, detail="The requested week is outside the supported date range.")
    connection = common.create_connection()
    try:
        return get_calendar_week(connection, week_start, include_exams=include_exams)
    finally:
        connection.close()


@router.put("/activities/{activity_id}/move")
def move_calendar_activity(activity_id: int, move_request: MoveActivityRequest):
    if move_request.activity_id != activity_id:
        raise HTTPException(
            status_code=400,
            detail="The activity ID in the URL and request body must match.",
        )

    connection = common.create_connection()

    try:
        moved_activity = move_activity(
            connection,
            activity_id,
            move_request.activity_type,
            move_request.destination_date,
            move_request.destination_weekday,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        connection.close()

    if moved_activity is None:
        raise HTTPException(status_code=404, detail="Activity not found.")

    return moved_activity
