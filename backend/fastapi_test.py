from fastapi import FastAPI

from backend.app.activities import get_all_activities
from backend.app.database import create_connection
from backend.app.calender import (
    check_activity_current,
    get_current_time,
    get_current_week,
    get_todays_activities,
    is_activity_on_date,
)

app = FastAPI()


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

    activities = get_all_activities(connection)
    current_week = get_current_week()
    activities_week = []

    for chosen_date in current_week:
        for activity in activities:
            activity_type = activity[2]
            activity_date = activity[3]
            activity_day = activity[4]

            if is_activity_on_date(
                activity_type,
                activity_date,
                activity_day,
                chosen_date,
            ):
                activities_week.append([
                    *activity,
                    str(chosen_date),
                ])

    connection.close()

    return activities_week
