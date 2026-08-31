from fastapi import FastAPI

from backend.app.database import create_connection
from backend.app.calender import get_todays_activities

app = FastAPI()


@app.get("/activities/today")
def todays_activities():
    connection = create_connection()

    activities = get_todays_activities(connection)

    connection.close()

    return activities