import os
import argparse
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

if __package__:
    from .ical_import import get_ical_events
    from .activities import add_activity
    from .database import create_connection
else:
    from ical_import import get_ical_events
    from activities import add_activity
    from database import create_connection


UOA_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AUCKLAND_TIMEZONE = ZoneInfo("Pacific/Auckland")


def get_uoa_timetable_events():
    load_dotenv(UOA_ENV_FILE)
    feed_url = os.getenv("UOA_TIMETABLE_URL", "").strip()

    if not feed_url:
        raise RuntimeError(
            "UOA_TIMETABLE_URL is missing. Add it to the project-root .env file."
        )

    return get_ical_events(feed_url, include_description=True)


def convert_uoa_event_to_activity(event):
    """Convert one dated class to the app's weekly activity format."""
    if not isinstance(event, dict):
        raise ValueError("The event must be a dictionary.")

    name = event.get("name") or event.get("summary")
    if not isinstance(name, str) or not name.strip() or name == "Untitled event":
        raise ValueError("The class name is missing.")
    name = name.strip()

    start = event.get("start")
    end = event.get("end")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValueError("A scheduled class needs both a start and an end datetime.")

    # Floating timetable times are local; timezone-aware values may be in UTC.
    start = (start.replace(tzinfo=AUCKLAND_TIMEZONE) if start.tzinfo is None
             else start.astimezone(AUCKLAND_TIMEZONE))
    end = (end.replace(tzinfo=AUCKLAND_TIMEZONE) if end.tzinfo is None
           else end.astimezone(AUCKLAND_TIMEZONE))
    start_time = start.strftime("%H:%M")
    end_time = end.strftime("%H:%M")

    if start.date() != end.date():
        raise ValueError("The existing weekly calendar cannot represent an overnight class.")
    if start_time >= end_time:
        raise ValueError("The class end time must be later than its start time.")

    subject = None
    # For example: PHYSICS 140/S2/C/LAB01/01 or COMPSCI 130 Lecture.
    for text in (name, event.get("description")):
        if isinstance(text, str):
            match = re.search(r"\b([A-Z][A-Z&]{1,11})\s*([0-9]{3}[A-Z]?)\b", text)
            if match:
                subject = f"{match.group(1)} {match.group(2)}"
                break

    weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    columns = [
        "name", "category", "subject", "activity_type", "date",
        "weekday", "start_time", "end_time",
    ]
    values = [
        name, "University", subject, "weekly", None,
        weekdays[start.weekday()], start_time, end_time,
    ]
    return columns, values


def import_uoa_timetable_to_activities(connection, events):
    imported = 0
    skipped = []
    repeated = 0
    seen_schedules = set()

    for event_number, event in enumerate(events, start=1):
        try:
            columns, values = convert_uoa_event_to_activity(event)
        except ValueError as error:
            reason = str(error)
            skipped.append({"event_number": event_number, "reason": reason})
            print(f"Skipped timetable event {event_number}: {reason}")
            continue

        # Several dated occurrences of one class become a single weekly row.
        # This only groups this batch; it does not perform database syncing.
        schedule = tuple(values)
        if schedule in seen_schedules:
            repeated += 1
            continue

        add_activity(connection, columns, values)
        seen_schedules.add(schedule)
        imported += 1

    print(f"Imported {imported} weekly activities; skipped {len(skipped)} invalid events "
          f"and {repeated} repeated weekly occurrences.")
    return {"imported": imported, "skipped": skipped, "repeated": repeated}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview or save UoA weekly classes.")
    parser.add_argument("--save", action="store_true", help="Save weekly classes to SQLite.")
    args = parser.parse_args()

    try:
        events = get_uoa_timetable_events()
    except RuntimeError as error:
        print(f"UoA timetable import failed: {error}")
        raise SystemExit(1)

    if not events:
        print("No UoA timetable events were found.")

    print("Converted activity preview (up to 5 events):")
    for event_number, event in enumerate(events[:5], start=1):
        try:
            columns, values = convert_uoa_event_to_activity(event)
            print(dict(zip(columns, values)))
        except ValueError as error:
            print(f"Skipped timetable event {event_number}: {error}")

    if args.save:
        connection = create_connection()
        try:
            import_uoa_timetable_to_activities(connection, events)
        finally:
            connection.close()
    else:
        print("Preview only. Run with --save to insert weekly activities into SQLite.")
