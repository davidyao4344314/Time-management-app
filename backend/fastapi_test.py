from datetime import date, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.app.activities import (
    add_activity,
    delete_activity,
    delte_all_activities,
    edit_activity,
    get_activities_by_name,
    get_activity_by_id,
    get_activity_name_by_id,
    get_all_activities,
    move_activity,
)
from backend.app.database import create_connection
from backend.app.calender import (
    check_activity_current,
    get_current_time,
    get_todays_activities,
    get_week_activities,
)
from backend.app.exams import (
    add_exam,
    delete_exam,
    edit_exam,
    get_all_exams,
    get_exam_by_id,
    get_exam_name_by_id,
    search_exams_by_name,
)

app = FastAPI()


class MoveActivityRequest(BaseModel):
    activity_id: int
    activity_type: str
    destination_date: str
    destination_weekday: str


class AddActivityRequest(BaseModel):
    name: str
    category: str
    subject: str | None = None
    activity_type: str
    date: str | None = None
    weekday: str | None = None
    start_time: str
    end_time: str


class EditActivityRequest(BaseModel):
    activity_id: int
    column_name: str
    new_value: str | None = None


class AddExamRequest(BaseModel):
    name: str
    category: str
    subject: str | None = None
    date: str
    start_time: str
    end_time: str


class EditExamRequest(BaseModel):
    exam_id: int
    column_name: str
    new_value: str | None = None


def activity_to_dict(activity):
    return {
        "id": activity[0],
        "name": activity[1],
        "category": activity[2],
        "subject": activity[3],
        "activity_type": activity[4],
        "date": activity[5],
        "weekday": activity[6],
        "start_time": activity[7],
        "end_time": activity[8],
    }


def exam_to_dict(exam):
    return {
        "id": exam[0],
        "name": exam[1],
        "category": exam[2],
        "subject": exam[3],
        "date": exam[4],
        "start_time": exam[5],
        "end_time": exam[6],
    }


@app.get("/exams")
def all_exams():
    connection = create_connection()

    try:
        exam_rows = get_all_exams(connection)
    finally:
        connection.close()

    return [exam_to_dict(exam) for exam in exam_rows]


@app.post("/exams", status_code=201)
def create_exam(exam_request: AddExamRequest):
    name = exam_request.name.strip()
    category = exam_request.category.strip()
    subject = exam_request.subject.strip() if exam_request.subject else None

    if not name or not category:
        raise HTTPException(status_code=400, detail="Name and category are required.")

    try:
        exam_date = str(date.fromisoformat(exam_request.date.strip()))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Date must use YYYY-MM-DD format.",
        ) from None

    try:
        start_time = datetime.strptime(exam_request.start_time.strip(), "%H:%M")
        end_time = datetime.strptime(exam_request.end_time.strip(), "%H:%M")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Start and end times must use HH:MM format.",
        ) from None

    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be later than start time.",
        )

    columns = [
        "name",
        "category",
        "subject",
        "date",
        "start_time",
        "end_time",
    ]
    values = [
        name,
        category,
        subject,
        exam_date,
        start_time.strftime("%H:%M"),
        end_time.strftime("%H:%M"),
    ]

    connection = create_connection()

    try:
        add_exam(connection, columns, values)
    finally:
        connection.close()

    return {"message": "Exam created."}


@app.get("/exams/search")
def search_exam_records_by_name(name: str):
    requested_name = name.strip()

    if not requested_name:
        raise HTTPException(status_code=400, detail="Exam name is required.")

    connection = create_connection()

    try:
        matching_exams = search_exams_by_name(connection, requested_name)
    finally:
        connection.close()

    return [exam_to_dict(exam) for exam in matching_exams]


@app.put("/exams/{exam_id}")
def update_exam(exam_id: int, edit_request: EditExamRequest):
    if edit_request.exam_id != exam_id:
        raise HTTPException(
            status_code=400,
            detail="The exam ID in the URL and request body must match.",
        )

    editable_columns = {
        "name",
        "category",
        "subject",
        "date",
        "start_time",
        "end_time",
    }
    column_name = edit_request.column_name.strip()

    if column_name not in editable_columns:
        raise HTTPException(status_code=400, detail="That field cannot be edited.")

    connection = create_connection()

    try:
        exam = get_exam_by_id(connection, exam_id)

        if exam is None:
            raise HTTPException(status_code=404, detail="Exam ID not found.")

        new_value = edit_request.new_value

        if column_name in {"name", "category"}:
            new_value = new_value.strip() if new_value else ""

            if not new_value:
                field_name = column_name.title()
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} is required.",
                )

        elif column_name == "subject":
            new_value = new_value.strip() if new_value else None

        elif column_name == "date":
            try:
                new_value = str(date.fromisoformat(new_value.strip()))
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="Date must use YYYY-MM-DD format.",
                ) from None

        elif column_name in {"start_time", "end_time"}:
            try:
                parsed_new_time = datetime.strptime(new_value.strip(), "%H:%M")
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="Time must use HH:MM format.",
                ) from None

            new_value = parsed_new_time.strftime("%H:%M")
            start_time_value = new_value if column_name == "start_time" else exam[5]
            end_time_value = new_value if column_name == "end_time" else exam[6]

            try:
                start_time = datetime.strptime(start_time_value, "%H:%M")
                end_time = datetime.strptime(end_time_value, "%H:%M")
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="The stored exam time is invalid.",
                ) from None

            if start_time >= end_time:
                raise HTTPException(
                    status_code=400,
                    detail="End time must be later than start time.",
                )

        edit_exam(connection, exam_id, column_name, new_value)
        updated_exam = get_exam_by_id(connection, exam_id)
    finally:
        connection.close()

    return exam_to_dict(updated_exam)


@app.delete("/exams/{exam_id}")
def remove_exam_by_id(exam_id: int):
    connection = create_connection()

    try:
        exam_name = get_exam_name_by_id(connection, exam_id)

        if exam_name is None:
            raise HTTPException(status_code=404, detail="Exam ID not found.")

        delete_exam(connection, exam_id)
    finally:
        connection.close()

    return {
        "message": "Exam deleted.",
        "exam_id": exam_id,
    }


@app.get("/activities")
def all_activities():
    connection = create_connection()

    activity_rows = get_all_activities(connection)

    connection.close()

    return [activity_to_dict(activity) for activity in activity_rows]


@app.post("/activities", status_code=201)
def create_activity(activity_request: AddActivityRequest):
    name = activity_request.name.strip()
    category = activity_request.category.strip()
    subject = activity_request.subject.strip() if activity_request.subject else None
    activity_type = activity_request.activity_type.strip().lower()

    if not name or not category:
        raise HTTPException(status_code=400, detail="Name and category are required.")

    if activity_type not in {"one_time", "daily", "weekly"}:
        raise HTTPException(status_code=400, detail="Invalid activity type.")

    try:
        start_time = datetime.strptime(
            activity_request.start_time.strip(),
            "%H:%M",
        )
        end_time = datetime.strptime(
            activity_request.end_time.strip(),
            "%H:%M",
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Start and end times must use HH:MM format.",
        ) from None

    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be later than start time.",
        )

    activity_date = None
    weekday = None

    if activity_type == "one_time":
        if not activity_request.date:
            raise HTTPException(
                status_code=400,
                detail="A date is required for a one-time activity.",
            )

        try:
            activity_date = str(date.fromisoformat(activity_request.date.strip()))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Date must use YYYY-MM-DD format.",
            ) from None

    elif activity_type == "weekly":
        valid_weekdays = {
            "monday": "Monday",
            "tuesday": "Tuesday",
            "wednesday": "Wednesday",
            "thursday": "Thursday",
            "friday": "Friday",
            "saturday": "Saturday",
            "sunday": "Sunday",
        }
        requested_weekday = (
            activity_request.weekday.strip().lower()
            if activity_request.weekday
            else ""
        )
        weekday = valid_weekdays.get(requested_weekday)

        if weekday is None:
            raise HTTPException(
                status_code=400,
                detail="A valid weekday is required for a weekly activity.",
            )

    columns = [
        "name",
        "category",
        "subject",
        "activity_type",
        "date",
        "weekday",
        "start_time",
        "end_time",
    ]
    values = [
        name,
        category,
        subject,
        activity_type,
        activity_date,
        weekday,
        start_time.strftime("%H:%M"),
        end_time.strftime("%H:%M"),
    ]

    connection = create_connection()

    try:
        add_activity(connection, columns, values)
        activity_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        created_activity = connection.execute(
            "SELECT * FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
    finally:
        connection.close()

    return activity_to_dict(created_activity)


@app.delete("/activities/all")
def remove_all_activities():
    connection = create_connection()

    try:
        deleted_count = len(get_all_activities(connection))
        delte_all_activities(connection)
    finally:
        connection.close()

    return {
        "message": "All activities deleted.",
        "deleted_count": deleted_count,
    }


@app.get("/activities/search")
def search_activities_by_name(name: str):
    requested_name = name.strip()

    if not requested_name:
        raise HTTPException(status_code=400, detail="Activity name is required.")

    connection = create_connection()

    try:
        matching_activities = get_activities_by_name(connection, requested_name)
    finally:
        connection.close()

    return [activity_to_dict(activity) for activity in matching_activities]


@app.put("/activities/{activity_id}")
def update_activity(activity_id: int, edit_request: EditActivityRequest):
    if edit_request.activity_id != activity_id:
        raise HTTPException(
            status_code=400,
            detail="The activity ID in the URL and request body must match.",
        )

    editable_columns = {
        "name",
        "category",
        "subject",
        "activity_type",
        "date",
        "weekday",
        "start_time",
        "end_time",
    }
    column_name = edit_request.column_name.strip()

    if column_name not in editable_columns:
        raise HTTPException(status_code=400, detail="That field cannot be edited.")

    connection = create_connection()

    try:
        activity = get_activity_by_id(connection, activity_id)

        if activity is None:
            raise HTTPException(status_code=404, detail="Activity ID not found.")

        current_activity_type = activity[4]
        new_value = edit_request.new_value

        if column_name in {"name", "category"}:
            new_value = new_value.strip() if new_value else ""

            if not new_value:
                field_name = column_name.replace("_", " ").title()
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} is required.",
                )

        elif column_name == "subject":
            new_value = new_value.strip() if new_value else None

        elif column_name == "activity_type":
            new_value = new_value.strip().lower() if new_value else ""

            if new_value not in {"one_time", "daily", "weekly"}:
                raise HTTPException(status_code=400, detail="Invalid activity type.")

        elif column_name == "date":
            if current_activity_type != "one_time":
                raise HTTPException(
                    status_code=400,
                    detail="Date can only be edited for a one-time activity.",
                )

            try:
                new_value = str(date.fromisoformat(new_value.strip()))
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="Date must use YYYY-MM-DD format.",
                ) from None

        elif column_name == "weekday":
            if current_activity_type != "weekly":
                raise HTTPException(
                    status_code=400,
                    detail="Weekday can only be edited for a weekly activity.",
                )

            valid_weekdays = {
                "monday": "Monday",
                "tuesday": "Tuesday",
                "wednesday": "Wednesday",
                "thursday": "Thursday",
                "friday": "Friday",
                "saturday": "Saturday",
                "sunday": "Sunday",
            }
            requested_weekday = new_value.strip().lower() if new_value else ""
            new_value = valid_weekdays.get(requested_weekday)

            if new_value is None:
                raise HTTPException(status_code=400, detail="Invalid weekday.")

        elif column_name in {"start_time", "end_time"}:
            try:
                parsed_new_time = datetime.strptime(new_value.strip(), "%H:%M")
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="Time must use HH:MM format.",
                ) from None

            new_value = parsed_new_time.strftime("%H:%M")
            start_time_value = new_value if column_name == "start_time" else activity[7]
            end_time_value = new_value if column_name == "end_time" else activity[8]

            try:
                start_time = datetime.strptime(start_time_value, "%H:%M")
                end_time = datetime.strptime(end_time_value, "%H:%M")
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="The stored activity time is invalid.",
                ) from None

            if start_time >= end_time:
                raise HTTPException(
                    status_code=400,
                    detail="End time must be later than start time.",
                )

        edit_activity(connection, activity_id, column_name, new_value)

        resulting_activity_type = (
            new_value if column_name == "activity_type" else current_activity_type
        )

        if resulting_activity_type == "one_time":
            edit_activity(connection, activity_id, "weekday", None)
        elif resulting_activity_type == "daily":
            edit_activity(connection, activity_id, "date", None)
            edit_activity(connection, activity_id, "weekday", None)
        elif resulting_activity_type == "weekly":
            edit_activity(connection, activity_id, "date", None)

        updated_activity = get_activity_by_id(connection, activity_id)
    finally:
        connection.close()

    return activity_to_dict(updated_activity)


@app.delete("/activities/{activity_id}")
def remove_activity_by_id(activity_id: int):
    connection = create_connection()

    try:
        activity_name = get_activity_name_by_id(connection, activity_id)

        if activity_name is None:
            raise HTTPException(status_code=404, detail="Activity ID not found.")

        delete_activity(connection, activity_id)
    finally:
        connection.close()

    return {
        "message": "Activity deleted.",
        "activity_id": activity_id,
    }


@app.get("/activities/today")
def todays_activities():
    connection = create_connection()

    activities = get_todays_activities(connection)

    connection.close()

    return [activity_to_dict(activity) for activity in activities]


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

    return [activity_to_dict(activity) for activity in activities_current]


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
