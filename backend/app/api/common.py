"""Shared HTTP response formatting and existing validation adapters."""
from fastapi import HTTPException

from backend.app.database import create_connection
from backend.app.planner import activity_service


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
        "active_start_date": activity[9],
        "active_end_date": activity[10],
        "source": activity[11],
        "external_id": activity[12],
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
        "source": exam[7],
        "external_id": exam[8],
    }


def normalize_optional_time(value):
    return activity_service.normalize_optional_time(value)


def validate_optional_time_range(start_time, end_time):
    # Exams retain the same HTTP helper and error response.
    try:
        activity_service.validate_optional_time_range(start_time, end_time)
    except activity_service.ActivityValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
