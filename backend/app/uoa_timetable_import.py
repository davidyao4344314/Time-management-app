import os
import argparse
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, set_key

if __package__:
    from .ical_import import get_ical_events
    from .activities import activity_exists, add_activity, backfill_activity_date_range, get_all_activities
    from .database import create_connection
else:
    from ical_import import get_ical_events
    from activities import activity_exists, add_activity, backfill_activity_date_range, get_all_activities
    from database import create_connection


UOA_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AUCKLAND_TIMEZONE = ZoneInfo("Pacific/Auckland")


def is_uoa_timetable_configured():
    load_dotenv(UOA_ENV_FILE)
    return bool(os.getenv("UOA_TIMETABLE_URL", "").strip())


def validate_uoa_timetable_url(feed_url):
    feed_url = feed_url.strip()
    message = "Enter a valid HTTP, HTTPS or webcal UoA timetable subscription URL."
    try:
        url = urlsplit(feed_url)
        valid = (
            url.scheme in {"http", "https", "webcal"}
            and url.hostname
            and not url.username
            and not url.password
            and not url.fragment
            and not any(character.isspace() for character in feed_url)
        )
        url.port  # Reject invalid ports without including the URL in an error.
    except ValueError:
        raise ValueError(message) from None
    if not valid:
        raise ValueError(message)
    return feed_url


def save_uoa_timetable_url(feed_url):
    feed_url = validate_uoa_timetable_url(feed_url)
    try:
        set_key(UOA_ENV_FILE, "UOA_TIMETABLE_URL", feed_url)
        UOA_ENV_FILE.chmod(0o600)
    except OSError:
        raise RuntimeError("Could not save the UoA timetable configuration.") from None
    os.environ["UOA_TIMETABLE_URL"] = feed_url


def get_uoa_timetable_events(feed_url=None):
    load_dotenv(UOA_ENV_FILE)
    if feed_url is None:
        feed_url = os.getenv("UOA_TIMETABLE_URL", "").strip()

    if not feed_url:
        raise RuntimeError(
            "UOA_TIMETABLE_URL is missing. Add it to the project-root .env file."
        )

    feed_url = validate_uoa_timetable_url(feed_url)
    return get_ical_events(feed_url, include_description=True)


def convert_uoa_event_to_activity(event):
    """Return activity columns and matching values without changing the raw event."""
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
        "name",
        "category",
        "subject",
        "activity_type",
        "date",
        "weekday",
        "start_time",
        "end_time",
        "active_start_date",
        "active_end_date",
    ]
    values = [
        name,
        "University",
        subject,
        "weekly",
        None,
        weekdays[start.weekday()],
        start_time,
        end_time,
        start.date().isoformat(),
        end.date().isoformat(),
    ]
    return columns, values


def prepare_uoa_activity_ranges(events):
    """Combine dated occurrences of the same class into a bounded weekly row.

    DTSTART/DTEND describe one class, not an entire semester. The inspected
    UoA feed lists each occurrence separately, so use its first and last dates.
    """
    schedules = {}
    skipped = []

    for event_number, event in enumerate(events, start=1):
        try:
            columns, values = convert_uoa_event_to_activity(event)
        except ValueError as error:
            reason = str(error)
            skipped.append({"event_number": event_number, "reason": reason})
            print(f"Skipped timetable event {event_number}: {reason}")
            continue

        # Match the eight original fields, never semester labels or row IDs.
        key = tuple(values[:8])
        if key not in schedules:
            schedules[key] = (columns, values)
        else:
            saved_values = schedules[key][1]
            saved_values[8] = min(saved_values[8], values[8])
            saved_values[9] = max(saved_values[9], values[9])

    return list(schedules.values()), skipped


def backfill_uoa_activity_ranges(connection, events):
    """Repair only legacy rows exactly matching the feed; keep all IDs/data."""
    schedules, skipped = prepare_uoa_activity_ranges(events)
    ranges = {tuple(values[:8]): values[8:] for _, values in schedules}
    updated = 0
    unmatched_ids = []
    with connection:
        for activity in get_all_activities(connection):
            if activity[2] != "University" or activity[4] != "weekly":
                continue
            if activity[9] is not None or activity[10] is not None:
                continue
            bounds = ranges.get(tuple(activity[1:9]))
            if bounds is None:
                unmatched_ids.append(activity[0])
                continue
            updated += backfill_activity_date_range(connection, activity[0], *bounds)
    return {"updated": updated, "unmatched_ids": unmatched_ids, "skipped": skipped}


def import_uoa_timetable_to_activities(connection, events):
    """Insert bounded weekly schedules using the existing activity function."""
    schedules, skipped = prepare_uoa_activity_ranges(events)
    imported = 0
    duplicates_skipped = 0
    for columns, values in schedules:
        if activity_exists(connection, columns, values):
            duplicates_skipped += 1
            continue
        add_activity(connection, columns, values)
        imported += 1

    print(f"Imported {imported} weekly activities; skipped {len(skipped)} invalid events.")
    print(f"Skipped {duplicates_skipped} duplicate timetable activities.")
    return {"imported": imported, "skipped": skipped, "duplicates_skipped": duplicates_skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview or save UoA weekly classes.")
    parser.add_argument("--save", action="store_true", help="Save weekly classes to SQLite.")
    args = parser.parse_args()

    try:
        events = get_uoa_timetable_events()
    except (RuntimeError, ValueError) as error:
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
