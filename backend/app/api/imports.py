"""Imports HTTP endpoints; business logic stays in backend services."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api import common
from sqlite3 import Error as SQLiteError
from pydantic import SecretStr
from backend.app.integrations.canvas_import import (
    get_canvas_events, is_canvas_calendar_configured, save_canvas_calendar_url,
    sort_out_canvas_events,
)
from backend.app.integrations.uoa_timetable_import import (
    get_uoa_timetable_events, import_uoa_timetable_to_activities,
    is_uoa_timetable_configured, save_uoa_timetable_url,
)

router = APIRouter()


@router.get("/canvas/status")
def canvas_status():
    return {"configured": is_canvas_calendar_configured()}


class CanvasImportRequest(BaseModel):
    calendar_url: SecretStr | None = None


@router.post("/canvas/import")
def import_canvas_calendar(import_request: CanvasImportRequest):
    calendar_url = (
        import_request.calendar_url.get_secret_value()
        if import_request.calendar_url is not None
        else None
    )

    if calendar_url is None and not is_canvas_calendar_configured():
        raise HTTPException(status_code=400, detail="Enter your Canvas iCal feed URL first.")

    try:
        events = get_canvas_events(calendar_url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid HTTPS Canvas iCal feed URL ending in .ics.",
        ) from None
    except (RuntimeError, TypeError, AttributeError):
        raise HTTPException(
            status_code=502,
            detail="Could not download or read the Canvas calendar. Check the feed URL and try again.",
        ) from None

    if calendar_url is not None:
        try:
            save_canvas_calendar_url(calendar_url)
        except RuntimeError:
            raise HTTPException(
                status_code=500,
                detail="Could not save the Canvas calendar configuration. Check local file permissions.",
            ) from None

    connection = None
    try:
        connection = common.create_connection()
        sort_out_canvas_events(connection, events)
    except (ValueError, SQLiteError):
        raise HTTPException(
            status_code=500,
            detail="Could not save all Canvas events. Check the event dates and database; some events may already have been saved.",
        ) from None
    finally:
        if connection is not None:
            connection.close()

    return {"message": "Canvas import completed."}


@router.get("/uoa/status")
def uoa_status():
    return {"configured": is_uoa_timetable_configured()}


class UoaImportRequest(BaseModel):
    timetable_url: SecretStr | None = None


@router.post("/uoa/import")
def import_uoa_timetable(import_request: UoaImportRequest):
    timetable_url = (
        import_request.timetable_url.get_secret_value()
        if import_request.timetable_url is not None
        else None
    )
    if timetable_url is None and not is_uoa_timetable_configured():
        raise HTTPException(status_code=400, detail="Enter your UoA timetable subscription URL first.")

    try:
        events = get_uoa_timetable_events(timetable_url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid HTTP, HTTPS or webcal UoA timetable subscription URL.",
        ) from None
    except (RuntimeError, TypeError, AttributeError):
        raise HTTPException(
            status_code=502,
            detail="Could not download or read the UoA timetable. Check your subscription URL and try again.",
        ) from None

    if timetable_url is not None:
        try:
            save_uoa_timetable_url(timetable_url)
        except RuntimeError:
            raise HTTPException(
                status_code=500,
                detail="Could not save the UoA timetable configuration. Check local file permissions.",
            ) from None

    connection = None
    try:
        connection = common.create_connection()
        result = import_uoa_timetable_to_activities(connection, events)
    except (ValueError, SQLiteError):
        raise HTTPException(
            status_code=500,
            detail="Could not save all timetable classes. Check the database; some classes may already have been saved.",
        ) from None
    finally:
        if connection is not None:
            connection.close()

    if result["imported"] == 0 and result["skipped"]:
        raise HTTPException(
            status_code=422,
            detail="No classes could be imported. The timetable events are missing valid names or start/end times.",
        )

    return {
        "message": "UoA timetable imported successfully.",
        "imported": result["imported"],
        "skipped": len(result["skipped"]),
    }
