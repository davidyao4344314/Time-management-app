from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.app.activities import get_all_activities, move_activity
from backend.app.database import create_connection
from backend.app.calender import (
    check_activity_current,
    get_current_time,
    get_todays_activities,
    get_week_activities,
)

app = FastAPI()


class MoveActivityRequest(BaseModel):
    activity_id: int
    activity_type: str
    destination_date: str
    destination_weekday: str


@app.get("/activities")
def all_activities():
    connection = create_connection()

    activity_rows = get_all_activities(connection)

    connection.close()

    return [
        {
            "id": activity[0],
            "name": activity[1],
            "category": activity[2],
            "subject": activity[3],
            "date": activity[4],
            "start_time": activity[5],
            "end_time": activity[6],
        }
        for activity in activity_rows
    ]


@app.get("/activities/today")
def todays_activities():
    connection = create_connection()

    activities = get_todays_activities(connection)

    connection.close()

    return activities


@app.get("/activities/current")
def current_activities():
    connection = create_connection()

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

    return activities_current


@app.get("/activities/week")
def weekly_activities():
    connection = create_connection()

    activities_week = get_week_activities(connection)

    connection.close()

    return activities_week


@app.put("/activities/{activity_id}/move")
def move_calendar_activity(activity_id: int, move_request: MoveActivityRequest):
    if move_request.activity_id != activity_id:
        raise HTTPException(
            status_code=400,
            detail="The activity ID in the URL and request body must match.",
        )

    connection = create_connection()

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
