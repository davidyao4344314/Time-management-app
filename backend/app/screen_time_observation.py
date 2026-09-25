"""Summarize stored Screen Time for a compact future-agent observation."""

from datetime import date, timedelta

from backend.app.screen_time import get_screen_time_range


_AVERAGE_FIELDS = (
    ("total_minutes", "avg_total_min"),
    ("productive_minutes", "avg_productive_min"),
    ("social_minutes", "avg_social_min"),
    ("entertainment_minutes", "avg_entertainment_min"),
    ("other_minutes", "avg_other_min"),
)


def build_screen_time_observation(connection, days=7):
    """Summarize the last `days` calendar dates, including today.

    Averages use recorded (non-NULL) values only. Missing values are not
    treated as zero; a field with no values returns None.
    """
    if type(days) is not int or days < 1:
        raise ValueError("days must be a positive integer.")

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    rows = get_screen_time_range(
        connection, start_date.isoformat(), end_date.isoformat()
    )

    observation = {"period_days": days, "recorded_days": len(rows)}
    for source_field, summary_field in _AVERAGE_FIELDS:
        values = [row[source_field] for row in rows if row[source_field] is not None]
        observation[summary_field] = round(sum(values) / len(values)) if values else None

    days_with_total = [row for row in rows if row["total_minutes"] is not None]
    highest = max(
        days_with_total,
        key=lambda row: (row["total_minutes"], row["date"]),
        default=None,
    )
    observation["highest_total_day"] = highest["date"] if highest else None
    observation["highest_total_min"] = highest["total_minutes"] if highest else None
    return observation


if __name__ == "__main__":
    import json
    import sqlite3

    from backend.app.database import create_tables
    from backend.app.screen_time import add_screen_time

    # This example uses only an in-memory database; it leaves saved data alone.
    samples = (
        (310, 90, 125, 60, 35),
        (250, 80, 80, 60, 30),
        (355, 100, 145, 70, 40),
        (280, 95, 105, 50, 30),
        (295, 90, 100, 75, 30),
        (260, 85, 90, 55, 30),
        (270, 100, 95, 45, 30),
    )
    connection = sqlite3.connect(":memory:")
    try:
        create_tables(connection)
        for index, minutes in enumerate(samples):
            sample_date = date.today() - timedelta(days=len(samples) - 1 - index)
            add_screen_time(connection, sample_date.isoformat(), *minutes)

        observation = build_screen_time_observation(connection)
        print(json.dumps(observation, indent=2))
    finally:
        connection.close()
