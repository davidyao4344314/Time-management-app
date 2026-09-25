"""Compact activity and calendar data for a future agent."""

from datetime import datetime

from backend.app.calender import (
    get_current_and_next_activities,
    get_current_date,
    get_current_time,
    get_week_activities,
    is_valid_activity_time,
)
from backend.app.observation_utils import chronological_key, compact_time as _time_or_none


def _brief_activity(activity):
    """Keep only schedule fields from a database activity tuple."""
    return {
        "name": activity[1],
        "start": _time_or_none(activity[7]),
        "end": _time_or_none(activity[8]),
    }


def _brief_occurrence(occurrence, include_date=False):
    brief = {"name": occurrence["name"]}
    if include_date:
        brief["date"] = occurrence["calendar_date"]
    brief["start"] = _time_or_none(occurrence["start_time"])
    brief["end"] = _time_or_none(occurrence["end_time"])
    return brief


def build_activity_observation(connection):
    """Summarize today and the seven calendar dates starting today.

    Current activities stay a list so overlapping activities remain visible.
    Date-only activities remain in today's/upcoming lists with null times.
    """
    today = get_current_date()
    today_string = today.isoformat()
    now = datetime.strptime(get_current_time(), "%H:%M").time()

    current, next_activity = get_current_and_next_activities(connection)
    occurrences = get_week_activities(connection, week_start=today)

    relevant = []
    for occurrence in occurrences:
        if occurrence["calendar_date"] == today_string and is_valid_activity_time(
            occurrence["start_time"], occurrence["end_time"]
        ):
            end = datetime.strptime(occurrence["end_time"].strip(), "%H:%M").time()
            if end <= now:
                continue
        relevant.append(occurrence)

    relevant.sort(key=lambda occurrence: chronological_key(
        occurrence["calendar_date"], occurrence["start_time"],
        occurrence["name"], occurrence["id"],
    ))
    current.sort(key=lambda activity: (
        _time_or_none(activity[7]) or "", activity[1], activity[0]
    ))

    return {
        "current": [_brief_activity(activity) for activity in current],
        "next": _brief_activity(next_activity) if next_activity else None,
        "today": [
            _brief_occurrence(occurrence)
            for occurrence in relevant
            if occurrence["calendar_date"] == today_string
        ],
        "upcoming_7d": [
            _brief_occurrence(occurrence, include_date=True)
            for occurrence in relevant[:20]
        ],
    }


if __name__ == "__main__":
    import json
    import sqlite3

    from backend.app.database import db_file

    # Read the existing database without changing any records or schema.
    connection = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        print(json.dumps(build_activity_observation(connection), indent=2))
    finally:
        connection.close()
