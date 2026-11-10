"""Shared HTTP response formatting and existing validation adapters."""
from fastapi import HTTPException

from backend.app.database import create_connection
from backend.app.planner import activity_service
from backend.app.planner.exams import exam_to_dict
from backend.app.planner.records import as_activity_record


def activity_to_dict(activity):
    return as_activity_record(activity)._asdict()


def normalize_optional_time(value):
    return activity_service.normalize_optional_time(value)


def validate_optional_time_range(start_time, end_time):
    # Exams retain the same HTTP helper and error response.
    try:
        activity_service.validate_optional_time_range(start_time, end_time)
    except activity_service.ActivityValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
