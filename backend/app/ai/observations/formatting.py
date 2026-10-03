"""Small formatting helpers shared by activity and exam observations."""

from datetime import datetime, timedelta


def compact_time(value):
    """Return a canonical HH:MM time, or None for missing/invalid values."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def chronological_key(calendar_date, start_time, name, identifier):
    """Sort by date and time, putting untimed items last on their date."""
    start = compact_time(start_time)
    return (calendar_date, start is None, start or "", name, identifier)


def observation_date_range(today, scope):
    """Return the remaining dates for a today, rolling-week, or month scope."""
    if scope == "today":
        return today, today
    if scope == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if scope in {"this_week", "next_week"}:
        monday = today - timedelta(days=today.weekday())
        if scope == "next_week":
            monday += timedelta(days=7)
        return monday, monday + timedelta(days=6)
    if scope == "week":
        return today, today + timedelta(days=6)
    if scope == "month":
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return today, next_month - timedelta(days=1)
    raise ValueError("Unknown observation date scope.")
