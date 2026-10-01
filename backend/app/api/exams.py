"""Exams HTTP endpoints; business logic stays in backend services."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api import common
from backend.app.planner import exam_service
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
    try:
        columns, values = exam_service.prepare_new_exam(exam_request.model_dump())
    except exam_service.ExamValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
    connection = common.create_connection()
    try:
        exam_service.add_exam(connection, columns, values)
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
    try:
        exam_service.validate_exam_edit(exam_id, edit_request.model_dump())
    except exam_service.ExamValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
    connection = common.create_connection()
    try:
        updated_exam = exam_service.update_exam_record(connection, exam_id, edit_request.model_dump())
    except exam_service.ExamValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
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
