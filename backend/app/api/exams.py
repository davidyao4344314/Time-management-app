"""Exams HTTP endpoints; business logic stays in backend services."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api import common
from datetime import date
from backend.app.planner.exams import (
    add_exam, delete_exam, edit_exam, get_all_exams, get_exam_by_id,
    get_exam_name_by_id, search_exams_by_name,
)

router = APIRouter()


class AddExamRequest(BaseModel):
    name: str
    category: str
    subject: str | None = None
    date: str
    start_time: str | None = None
    end_time: str | None = None


class EditExamRequest(BaseModel):
    exam_id: int
    column_name: str
    new_value: str | None = None


@router.get("/exams")
def all_exams():
    connection = common.create_connection()

    try:
        exam_rows = get_all_exams(connection)
    finally:
        connection.close()

    return [common.exam_to_dict(exam) for exam in exam_rows]


@router.post("/exams", status_code=201)
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
        start_time = common.normalize_optional_time(exam_request.start_time)
        end_time = common.normalize_optional_time(exam_request.end_time)
    except (AttributeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Times must use HH:MM format.",
        ) from None

    common.validate_optional_time_range(start_time, end_time)

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

    connection = common.create_connection()

    try:
        add_exam(connection, columns, values)
    finally:
        connection.close()

    return {"message": "Exam created."}


@router.get("/exams/search")
def search_exam_records_by_name(name: str):
    requested_name = name.strip()

    if not requested_name:
        raise HTTPException(status_code=400, detail="Exam name is required.")

    connection = common.create_connection()

    try:
        matching_exams = search_exams_by_name(connection, requested_name)
    finally:
        connection.close()

    return [common.exam_to_dict(exam) for exam in matching_exams]


@router.put("/exams/{exam_id}")
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

    connection = common.create_connection()

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
                new_value = common.normalize_optional_time(new_value)
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="Time must use HH:MM format.",
                ) from None

            start_time_value = new_value if column_name == "start_time" else exam[5]
            end_time_value = new_value if column_name == "end_time" else exam[6]

            try:
                start_time_value = common.normalize_optional_time(start_time_value)
                end_time_value = common.normalize_optional_time(end_time_value)
            except (AttributeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="The stored exam time is invalid.",
                ) from None

            common.validate_optional_time_range(start_time_value, end_time_value)

        edit_exam(connection, exam_id, column_name, new_value)
        updated_exam = get_exam_by_id(connection, exam_id)
    finally:
        connection.close()

    return common.exam_to_dict(updated_exam)


@router.delete("/exams/{exam_id}")
def remove_exam_by_id(exam_id: int):
    connection = common.create_connection()

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
