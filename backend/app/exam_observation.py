"""Compact upcoming exams and tests for a future agent."""

from datetime import date, timedelta

from backend.app.calender import get_current_date, get_current_time
from backend.app.exams import get_all_exams
from backend.app.observation_utils import chronological_key, compact_time


def _exam_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value.strip() else None


def build_exam_observation(connection):
    """Return relevant exams from today through 30 days ahead, at most 20 detailed."""
    today = get_current_date()
    end_date = today + timedelta(days=30)
    current_time = get_current_time()
    relevant = []
    seen = set()

    for exam in get_all_exams(connection):
        exam_date = _exam_date(exam[4])
        if exam_date is None or not today <= exam_date <= end_date:
            continue

        # A date-only exam remains relevant all day. A timed exam that has
        # already ended today is no longer upcoming.
        end_time = compact_time(exam[6])
        if exam_date == today and end_time is not None and end_time <= current_time:
            continue

        # Equivalent imported rows should occupy only one place in the compact
        # observation. This does not alter the database or hide distinct exams.
        exam_fields = exam[1:7]  # name, category, subject, date, start, end
        if exam_fields in seen:
            continue
        seen.add(exam_fields)
        relevant.append((exam, exam_date))

    relevant.sort(key=lambda item: chronological_key(
        item[1].isoformat(), item[0][5], item[0][1], item[0][0],
    ))

    return {
        "upcoming": [
            {
                "name": exam[1],
                "subject": exam[3],
                "date": exam_date.isoformat(),
                "start": compact_time(exam[5]),
                "end": compact_time(exam[6]),
                "days_left": (exam_date - today).days,
            }
            for exam, exam_date in relevant[:20]
        ],
        "count": len(relevant),
    }


if __name__ == "__main__":
    import json
    import sqlite3

    from backend.app.database import db_file

    # Read the existing database without changing any records or schema.
    connection = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        print(json.dumps(build_exam_observation(connection), indent=2))
    finally:
        connection.close()
