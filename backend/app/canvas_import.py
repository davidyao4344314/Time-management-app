import os
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from icalendar import Calendar

try:
    from backend.app.activities import add_activity
    from backend.app.exams import add_exam
except ModuleNotFoundError:
    # Keep direct execution working: python backend/app/canvas_import.py
    from activities import add_activity
    from exams import add_exam


def get_canvas_events():
    project_directory = Path(__file__).resolve().parents[2]
    load_dotenv(project_directory / ".env")

    calendar_url = os.getenv("CANVAS_CALENDAR_URL", "").strip()

    if not calendar_url:
        raise RuntimeError(
            "CANVAS_CALENDAR_URL is missing. Add it to the project .env file."
        )

    try:
        response = requests.get(calendar_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError("Could not download the Canvas calendar feed.") from None

    try:
        calendar = Calendar.from_ical(response.content)
    except Exception:
        raise RuntimeError("Could not parse the Canvas calendar feed.") from None

    events = []

    for component in calendar.walk("VEVENT"):
        summary = component.get("summary")
        start = component.get("dtstart")
        end = component.get("dtend")
        uid = component.get("uid")

        events.append({
            "name": str(summary) if summary else "Untitled event",
            "start": start.dt if start else None,
            "end": end.dt if end else None,
            "external_id": str(uid) if uid else None,
        })

    return events

def convert_canvas_event_to_exam(event):
    event_date, start_time, end_time = get_canvas_event_schedule(event)

    columns = [
        "name",
        "category",
        "subject",
        "date",
        "start_time",
        "end_time",
    ]
    values = [
        event.get("name", "Untitled event"),
        "Canvas",
        get_subject_from_name(event.get("name", "")),
        event_date,
        start_time,
        end_time,
    ]

    return columns, values


def convert_canvas_event_to_activity(event):
    event_date, start_time, end_time = get_canvas_event_schedule(event)

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
        event.get("name", "Untitled event"),
        "Canvas",
        get_subject_from_name(event.get("name", "")),
        "one_time",
        event_date,
        None,
        start_time,
        end_time,
    ]

    return columns, values


def get_canvas_event_schedule(event):
    start = event.get("start")
    end = event.get("end")

    if isinstance(start, datetime):
        event_date = start.date().isoformat()
        start_time = start.strftime("%H:%M")
    elif isinstance(start, date):
        event_date = start.isoformat()
        start_time = None
    else:
        event_date = None
        start_time = None

    if isinstance(end, datetime):
        end_time = end.strftime("%H:%M")
    else:
        end_time = None

    return event_date, start_time, end_time


def get_subject_from_name(name):
    if "[" in name and "]" in name:
        start = name.rfind("[")
        end = name.rfind("]")

        if end > start:
            subject = name[start + 1:end].strip()
            return subject or None

    return None


def check_canvas_event_matches_schema(event_type, columns, values):
    converted_event = dict(zip(columns, values))

    if converted_event.get("date") is None:
        raise ValueError(
            f"Cannot import Canvas {event_type} {converted_event['name']!r}: "
            "the event does not contain a usable start date."
        )

    if (
        converted_event.get("start_time") is None
        or converted_event.get("end_time") is None
    ):
        raise ValueError(
            f"Cannot import Canvas {event_type} {converted_event['name']!r}: "
            "the current database requires both start_time and end_time, "
            "but this event does not provide both times."
        )
if __name__ == "__main__":
    try:
        canvas_events = get_canvas_events()
    except RuntimeError as error:
        print(f"Canvas import failed: {error}")
    else:
        if not canvas_events:
            print("No Canvas events were found.")

        for event_number, event in enumerate(canvas_events, start=1):
            print(f"Event {event_number}")
            print(f"  Name: {event['name']}")
            print(f"  Start: {event['start']}")
            print(f"  End: {event['end']}")
            print(f"  External ID: {event['external_id']}")
            print()
def classify_canvas_event(event):
    name = event["name"].lower()

    if "exam" in name or "test" in name or "quiz" in name or "assignment" in name:
        return "exam"

    elif "lab" in name or "tutorial" in name or "workshop" in name:
        return "activity"

    return "unknown"

def sort_out_canvas_events(connection, events):
    for event in events:
        event_type = classify_canvas_event(event)

        if event_type == "exam":
            columns, values = convert_canvas_event_to_exam(event)
            check_canvas_event_matches_schema(event_type, columns, values)
            add_exam(connection, columns, values)

        elif event_type == "activity":
            columns, values = convert_canvas_event_to_activity(event)
            check_canvas_event_matches_schema(event_type, columns, values)
            add_activity(connection, columns, values)

        else:
            continue
