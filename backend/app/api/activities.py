"""Activities HTTP endpoints; business logic stays in backend services."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api import common
from sqlite3 import Error as SQLiteError
from backend.app.planner import activity_service
from backend.app.planner.activities import (
    delete_activity, delte_all_activities, get_activities_by_name,
    get_activity_name_by_id, get_all_activities, remove_duplicate_activities,
)

router = APIRouter()


class AddActivityRequest(BaseModel):
    name: str
    category: str
    subject: str | None = None
    activity_type: str
    date: str | None = None
    weekday: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class EditActivityRequest(BaseModel):
    activity_id: int
    column_name: str
    new_value: str | None = None
    date: str | None = None
    weekday: str | None = None


@router.get("/activities")
def all_activities():
    connection = common.create_connection()

    activity_rows = get_all_activities(connection)

    connection.close()

    return [common.activity_to_dict(activity) for activity in activity_rows]


@router.post("/activities", status_code=201)
def create_activity(activity_request: AddActivityRequest):
    try:
        prepared = activity_service.prepare_new_activity(activity_request.model_dump())
    except activity_service.ActivityValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None

    connection = common.create_connection()
    try:
        created_activity = activity_service.create_activity_record(connection, prepared)
    finally:
        connection.close()
    return common.activity_to_dict(created_activity)


@router.post("/activities/remove-duplicates")
def clear_duplicate_activities():
    connection = None
    try:
        connection = common.create_connection()
        number_removed = remove_duplicate_activities(connection)
    except SQLiteError:
        raise HTTPException(
            status_code=500,
            detail="Could not remove duplicate activities. Please try again.",
        ) from None
    finally:
        if connection is not None:
            connection.close()

    return {"number_removed": number_removed}


@router.delete("/activities/all")
def remove_all_activities():
    connection = common.create_connection()

    try:
        deleted_count = len(get_all_activities(connection))
        delte_all_activities(connection)
    finally:
        connection.close()

    return {
        "message": "All activities deleted.",
        "deleted_count": deleted_count,
    }


@router.get("/activities/search")
def search_activities_by_name(name: str):
    requested_name = name.strip()

    if not requested_name:
        raise HTTPException(status_code=400, detail="Activity name is required.")

    connection = common.create_connection()

    try:
        matching_activities = get_activities_by_name(connection, requested_name)
    finally:
        connection.close()

    return [common.activity_to_dict(activity) for activity in matching_activities]


@router.put("/activities/{activity_id}")
def update_activity(activity_id: int, edit_request: EditActivityRequest):
    fields = edit_request.model_dump()
    try:
        # Preserve validation-before-connection for ID/column errors.
        activity_service.validate_activity_edit(activity_id, fields)
    except activity_service.ActivityValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None

    connection = common.create_connection()
    try:
        updated_activity = activity_service.update_activity_record(connection, activity_id, fields)
    except activity_service.ActivityValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
    finally:
        connection.close()
    return common.activity_to_dict(updated_activity)


@router.delete("/activities/{activity_id}")
def remove_activity_by_id(activity_id: int):
    connection = common.create_connection()

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
