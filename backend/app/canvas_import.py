import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv, set_key

if __package__:
    from .ical_import import get_ical_events
else:
    from ical_import import get_ical_events

try:
    from backend.app.activities import activity_exists, add_activity
    from backend.app.exams import add_exam, exam_exists
except ModuleNotFoundError:
    # Keep direct execution working: python backend/app/canvas_import.py
    from activities import activity_exists, add_activity
    from exams import add_exam, exam_exists


CANVAS_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def is_canvas_calendar_configured():
    load_dotenv(CANVAS_ENV_FILE)

    return bool(os.getenv("CANVAS_CALENDAR_URL", "").strip())


def validate_canvas_calendar_url(calendar_url):
    calendar_url = calendar_url.strip()
    error_message = "Enter a valid HTTPS Canvas iCal feed URL ending in .ics."

    try:
        parsed_url = urlsplit(calendar_url)
        valid = (
            parsed_url.scheme == "https"
            and parsed_url.hostname
            and parsed_url.path.lower().endswith(".ics")
            and not parsed_url.username
            and not parsed_url.password
            and not parsed_url.fragment
            and not any(character.isspace() for character in calendar_url)
        )
    except ValueError:
        raise ValueError(error_message) from None

    if not valid:
        raise ValueError(error_message)

    return calendar_url


def save_canvas_calendar_url(calendar_url):
    calendar_url = validate_canvas_calendar_url(calendar_url)

    try:
        set_key(CANVAS_ENV_FILE, "CANVAS_CALENDAR_URL", calendar_url)
        CANVAS_ENV_FILE.chmod(0o600)
    except OSError:
        raise RuntimeError("Could not save the Canvas calendar configuration.") from None

    # Also update this running process, so another import uses the new URL.
    os.environ["CANVAS_CALENDAR_URL"] = calendar_url


def get_canvas_events(calendar_url=None):
    load_dotenv(CANVAS_ENV_FILE)

    if calendar_url is None:
        calendar_url = os.getenv("CANVAS_CALENDAR_URL", "").strip()

    if not calendar_url:
        raise RuntimeError(
            "CANVAS_CALENDAR_URL is missing. Add it to the project .env file."
        )

    calendar_url = validate_canvas_calendar_url(calendar_url)

    return get_ical_events(calendar_url)

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
    imported = 0
    duplicates_skipped = 0
    for event in events:
        event_type = classify_canvas_event(event)

        if event_type == "exam":
            columns, values = convert_canvas_event_to_exam(event)
            check_canvas_event_matches_schema(event_type, columns, values)
            if exam_exists(connection, columns, values):
                duplicates_skipped += 1
                continue
            add_exam(connection, columns, values)

        elif event_type == "activity":
            columns, values = convert_canvas_event_to_activity(event)
            check_canvas_event_matches_schema(event_type, columns, values)
            if activity_exists(connection, columns, values):
                duplicates_skipped += 1
                continue
            add_activity(connection, columns, values)

        else:
            continue
        imported += 1

    print(f"Imported {imported} Canvas events; skipped {duplicates_skipped} duplicates.")
    return {"imported": imported, "duplicates_skipped": duplicates_skipped}
