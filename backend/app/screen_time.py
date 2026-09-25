"""Store and retrieve daily Screen Time summaries."""

from datetime import date as CalendarDate


_COLUMNS = (
    "id", "date", "total_minutes", "productive_minutes", "social_minutes",
    "entertainment_minutes", "other_minutes",
)


def _valid_date(value):
    if not isinstance(value, str):
        raise ValueError("Date must use YYYY-MM-DD format.")
    try:
        parsed = CalendarDate.fromisoformat(value)
    except ValueError:
        raise ValueError("Date must use YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ValueError("Date must use YYYY-MM-DD format.")
    return value


def _valid_minutes(value, field_name):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{field_name} must be a non-negative integer or None.")
    return value


def _as_dict(row):
    return dict(zip(_COLUMNS, row)) if row is not None else None


def add_screen_time(
    connection, date, total_minutes=None, productive_minutes=None,
    social_minutes=None, entertainment_minutes=None, other_minutes=None,
):
    """Insert one day or update that date's existing row; keep its ID."""
    values = (
        _valid_date(date),
        _valid_minutes(total_minutes, "total_minutes"),
        _valid_minutes(productive_minutes, "productive_minutes"),
        _valid_minutes(social_minutes, "social_minutes"),
        _valid_minutes(entertainment_minutes, "entertainment_minutes"),
        _valid_minutes(other_minutes, "other_minutes"),
    )
    with connection:
        connection.execute("""
            INSERT INTO screen_time_daily (
                date, total_minutes, productive_minutes, social_minutes,
                entertainment_minutes, other_minutes
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_minutes = excluded.total_minutes,
                productive_minutes = excluded.productive_minutes,
                social_minutes = excluded.social_minutes,
                entertainment_minutes = excluded.entertainment_minutes,
                other_minutes = excluded.other_minutes
        """, values)
        row = connection.execute(
            "SELECT id FROM screen_time_daily WHERE date = ?", (date,)
        ).fetchone()
    return row[0]


def get_screen_time_by_date(connection, date):
    """Return one daily summary as a dictionary, or None if absent."""
    row = connection.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM screen_time_daily WHERE date = ?",
        (_valid_date(date),),
    ).fetchone()
    return _as_dict(row)


def get_screen_time_range(connection, start_date, end_date):
    """Return summaries for the inclusive date range, sorted oldest first."""
    first = _valid_date(start_date)
    last = _valid_date(end_date)
    if first > last:
        raise ValueError("start_date must not be after end_date.")
    rows = connection.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM screen_time_daily "
        "WHERE date BETWEEN ? AND ? ORDER BY date",
        (first, last),
    ).fetchall()
    return [_as_dict(row) for row in rows]


if __name__ == "__main__":
    import sqlite3

    from backend.app.database import create_tables

    # Keep the manual example out of the real project database.
    connection = sqlite3.connect(":memory:")
    try:
        create_tables(connection)
        add_screen_time(connection, "2026-09-25", 310, 90, 125, 60, 35)
        print(get_screen_time_by_date(connection, "2026-09-25"))
    finally:
        connection.close()
