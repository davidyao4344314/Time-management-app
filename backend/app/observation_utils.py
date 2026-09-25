"""Small formatting helpers shared by activity and exam observations."""

from datetime import datetime


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
