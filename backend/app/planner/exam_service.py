"""Exam validation and updates, independent of HTTP and AI."""

from datetime import date
from backend.app.planner.activity_service import (
    ActivityValidationError, normalize_optional_time, validate_optional_time_range,
)
from backend.app.planner.exams import add_exam, edit_exam, get_exam_by_id

# Shared validation error contract, translated only at the HTTP boundary.
ExamValidationError = ActivityValidationError


def prepare_new_exam(fields):
    name = fields.get("name").strip()
    category = fields.get("category").strip()
    subject = fields.get("subject").strip() if fields.get("subject") else None

    if not name or not category:
        raise ExamValidationError(status_code=400, detail="Name and category are required.")

    try:
        exam_date = str(date.fromisoformat(fields.get("date").strip()))
    except ValueError:
        raise ExamValidationError(
            status_code=400,
            detail="Date must use YYYY-MM-DD format.",
        ) from None

    try:
        start_time = normalize_optional_time(fields.get("start_time"))
        end_time = normalize_optional_time(fields.get("end_time"))
    except (AttributeError, ValueError):
        raise ExamValidationError(
            status_code=400,
            detail="Times must use HH:MM format.",
        ) from None

    validate_optional_time_range(start_time, end_time)

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
        start_time,
        end_time,
    ]

    return columns, values


def validate_exam_edit(exam_id, fields):
    if fields.get("exam_id") != exam_id:
        raise ExamValidationError(
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
    column_name = fields.get("column_name").strip()

    if column_name not in editable_columns:
        raise ExamValidationError(status_code=400, detail="That field cannot be edited.")

    return column_name


def update_exam_record(connection, exam_id, fields):
    column_name = validate_exam_edit(exam_id, fields)

    exam = get_exam_by_id(connection, exam_id)

    if exam is None:
        raise ExamValidationError(status_code=404, detail="Exam ID not found.")

    new_value = fields.get("new_value")

    if column_name in {"name", "category"}:
        new_value = new_value.strip() if new_value else ""

        if not new_value:
            field_name = column_name.title()
            raise ExamValidationError(
                status_code=400,
                detail=f"{field_name} is required.",
            )

    elif column_name == "subject":
        new_value = new_value.strip() if new_value else None

    elif column_name == "date":
        try:
            new_value = str(date.fromisoformat(new_value.strip()))
        except (AttributeError, ValueError):
            raise ExamValidationError(
                status_code=400,
                detail="Date must use YYYY-MM-DD format.",
            ) from None

    elif column_name in {"start_time", "end_time"}:
        try:
            new_value = normalize_optional_time(new_value)
        except (AttributeError, ValueError):
            raise ExamValidationError(
                status_code=400,
                detail="Time must use HH:MM format.",
            ) from None

        start_time_value = new_value if column_name == "start_time" else exam[5]
        end_time_value = new_value if column_name == "end_time" else exam[6]

        try:
            start_time_value = normalize_optional_time(start_time_value)
            end_time_value = normalize_optional_time(end_time_value)
        except (AttributeError, ValueError):
            raise ExamValidationError(
                status_code=400,
                detail="The stored exam time is invalid.",
            ) from None

        validate_optional_time_range(start_time_value, end_time_value)

    edit_exam(connection, exam_id, column_name, new_value)
    updated_exam = get_exam_by_id(connection, exam_id)

    return updated_exam
