from fastapi import FastAPI

from backend.app.activities import get_all_activities
from backend.app.database import create_connection
from backend.app.calender import (
    check_activity_current,
    get_current_time,
    get_todays_activities,
    get_week_activities,
)

app = FastAPI()


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
