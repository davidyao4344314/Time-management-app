"""Read-only activity overlap checks, separate from CRUD and HTTP handling.

Return one representative conflicting date per existing activity, not every
occurrence of an unbounded recurrence. A one-time date is checked directly.
For recurring pairs, check up to seven dates in their shared active range
(starting today when both ranges are unrestricted). The existing calendar
predicate resolves the actual occurrences; no weekday rules are duplicated.
"""

from datetime import date, datetime, timedelta

from backend.app.planner import calendar
from backend.app.planner.activities import get_all_activities


def _time_range(activity):
    start, end = activity.get("start_time"), activity.get("end_time")
    if not calendar.is_valid_activity_time(start, end):
        return None
    return (
        datetime.strptime(start.strip(), "%H:%M").time(),
        datetime.strptime(end.strip(), "%H:%M").time(),
    )


def _date_bounds(activity):
    """Bound the search only; calendar.is_activity_on_date remains authoritative."""
    activity_type = activity.get("activity_type")
    if not isinstance(activity_type, str):
        return None
    activity_type = activity_type.strip().lower()
    try:
        if activity_type == "one_time":
            day = datetime.strptime(activity.get("date").strip(), "%Y-%m-%d").date()
            return day, day
        if activity_type == "daily":
            return date.min, date.max
        if activity_type == "weekly":
            start = activity.get("active_start_date")
            end = activity.get("active_end_date")
            if start is None and end is None:
                return date.min, date.max
            first = datetime.strptime(start, "%Y-%m-%d").date()
            last = datetime.strptime(end, "%Y-%m-%d").date()
            return (first, last) if first <= last else None
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _occurs_on(activity, chosen_date):
    return calendar.is_activity_on_date(
        activity.get("activity_type"), activity.get("date"),
        activity.get("weekday"), chosen_date,
        activity.get("active_start_date"), activity.get("active_end_date"),
    )


def _first_shared_date(candidate, existing, candidate_bounds, existing_bounds, today):
    first = max(candidate_bounds[0], existing_bounds[0])
    last = min(candidate_bounds[1], existing_bounds[1])
    if first == date.min and last == date.max:
        first = today
    if first > last:
        return None
    # Daily/weekly schedules repeat within seven days. One-time bounds contain
    # exactly one date. Also clamp to date.max to avoid overflowing datetime.
    for offset in range(min(7, (last - first).days + 1)):
        chosen_date = first + timedelta(days=offset)
        if _occurs_on(candidate, chosen_date) and _occurs_on(existing, chosen_date):
            return chosen_date
    return None


def find_activity_conflicts(connection, candidate_activity, exclude_activity_id=None):
    """Check a candidate dictionary without inserting, updating or committing.

    Include active_start_date/active_end_date when checking an imported weekly
    activity. Exclusion is explicit: pass its stored ID when checking an edit.
    Invalid/date-only time ranges and unusable dates are safely ignored. Exams
    are not checked. Results are JSON-friendly and sorted by date, time and ID.
    """
    candidate_times = _time_range(candidate_activity)
    candidate_bounds = _date_bounds(candidate_activity)
    if candidate_times is None or candidate_bounds is None:
        return []

    candidate_start, candidate_end = candidate_times
    today = calendar.get_current_date()
    conflicts = []
    for row in get_all_activities(connection):
        if row[0] == exclude_activity_id:
            continue
        # The inspected schema keeps schedule fields at positions 4–10.
        # Later source/external metadata is intentionally not part of a check.
        existing = dict(zip(
            ("activity_type", "date", "weekday", "start_time", "end_time",
             "active_start_date", "active_end_date"),
            row[4:11],
        ))
        existing_times = _time_range(existing)
        existing_bounds = _date_bounds(existing)
        if existing_times is None or existing_bounds is None:
            continue
        existing_start, existing_end = existing_times
        if not (candidate_start < existing_end and candidate_end > existing_start):
            continue
        shared_date = _first_shared_date(
            candidate_activity, existing, candidate_bounds, existing_bounds, today,
        )
        if shared_date is not None:
            conflicts.append({
                "activity_id": row[0],
                "name": row[1],
                "date": shared_date.isoformat(),
                "start_time": existing_start.strftime("%H:%M"),
                "end_time": existing_end.strftime("%H:%M"),
            })
    return sorted(conflicts, key=lambda item: (
        item["date"], item["start_time"], item["activity_id"],
    ))
