"""Compact activity and calendar data for a future agent."""

from datetime import datetime, timedelta

from backend.app.planner.activities import get_all_activities
from backend.app.planner.calendar import (
    get_current_and_next_activities,
    get_current_date,
    get_current_time,
    get_week_activities,
    is_valid_activity_time,
)
from backend.app.ai.observations.formatting import (
    chronological_key,
    compact_time as _time_or_none,
    observation_date_range,
    bounded_details,
)


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


def _occurrences_in_range(connection, first_date, last_date):
    """Ask the existing calendar logic for each chunk of up to seven dates."""
    occurrences = []
    days = (last_date - first_date).days + 1
    for offset in range(0, days, 7):
        week_start = first_date + timedelta(days=offset)
        occurrences.extend(
            occurrence for occurrence in get_week_activities(connection, week_start)
            if occurrence["calendar_date"] <= last_date.isoformat()
        )
    return occurrences


def _brief_activity_definition(activity):
    """Represent an explicitly requested full activity list without IDs or metadata."""
    return {
        "name": activity[1],
        "category": activity[2],
        "subject": activity[3],
        "activity_type": activity[4],
        "date": activity[5],
        "weekday": activity[6],
        "start": _time_or_none(activity[7]),
        "end": _time_or_none(activity[8]),
        "active_start_date": activity[9] if len(activity) > 9 else None,
        "active_end_date": activity[10] if len(activity) > 10 else None,
    }


def _busy_ranges(occurrences):
    """Complete union of occupied times, including occurrences omitted from detail."""
    days = {}
    untimed = 0
    for item in occurrences:
        if not is_valid_activity_time(item['start_time'], item['end_time']):
            untimed += 1
            continue
        days.setdefault(item['calendar_date'], []).append((
            _time_or_none(item['start_time']), _time_or_none(item['end_time'])))
    busy = {}
    for day, ranges in sorted(days.items()):
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        busy[day] = merged
    return busy, untimed


def build_activity_observation(connection, scope="week"):
    """Summarize the requested date window, or all activity definitions.

    Current activities stay a list so overlapping activities remain visible.
    Date-only activities remain in the lists with null times. The default
    preserves the existing seven-day observation structure.
    """
    if scope == "all":
        activities = get_all_activities(connection)
        detailed = bounded_details(_brief_activity_definition(activity) for activity in activities)
        return {
            "all_activities": detailed,
            "count": len(activities),
            "truncated": len(detailed) < len(activities),
            "coverage": 'activity definitions, not availability; request a date window for free time',
        }

    today = get_current_date()
    first_date, last_date = observation_date_range(today, scope)
    today_string = today.isoformat()
    now = datetime.strptime(get_current_time(), "%H:%M").time()

    current, next_activity = get_current_and_next_activities(connection)
    occurrences = _occurrences_in_range(connection, first_date, last_date)

    relevant = []
    for occurrence in occurrences:
        if occurrence["calendar_date"] < today_string:
            continue
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

    today_items = [_brief_occurrence(item) for item in relevant
                   if item['calendar_date'] == today_string]
    current_items = bounded_details(_brief_activity(item) for item in current)
    busy, untimed = _busy_ranges(relevant)
    observation = {
        "current": current_items,
        "current_count": len(current),
        "next": _brief_activity(next_activity) if next_activity else None,
        "today": bounded_details(today_items),
        "today_count": len(today_items),
        "period": {'start': max(first_date, today).isoformat(), 'end': last_date.isoformat()},
        "count": len(relevant),
        "busy": busy,
        "untimed_count": untimed,
        "truncated": len(current_items) < len(current) or len(bounded_details(today_items)) < len(today_items),
    }
    if scope == "today":
        return observation

    # Keep the original 20-occurrence limit for the default seven-day view.
    # An explicitly requested month includes the whole remaining month.
    detailed = bounded_details(_brief_occurrence(item, include_date=True) for item in relevant)
    observation["upcoming_month" if scope == "month" else "upcoming_7d"] = detailed
    observation['truncated'] |= len(detailed) < len(relevant)
    return observation


def main():
    import json
    import sqlite3

    from backend.app.database import db_file

    # Read the existing database without changing any records or schema.
    connection = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        print(json.dumps(build_activity_observation(connection), indent=2))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
