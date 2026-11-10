"""Occurrence-level completion records for the local, shared planner."""

from datetime import date

from backend.app.infrastructure.clock import local_now
from backend.app.planner.activities import get_all_activities
from backend.app.planner.calendar import is_activity_on_date


class SessionValidationError(ValueError):
    pass


class SessionNotFoundError(ValueError):
    pass


def migrate(connection, *, commit=True):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            session_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('done', 'partly_done', 'missed')),
            actual_minutes INTEGER NOT NULL CHECK (actual_minutes BETWEEN 0 AND 1440),
            name TEXT NOT NULL,
            subject TEXT,
            category TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (activity_id, session_date),
            CHECK ((status = 'missed' AND actual_minutes = 0)
                OR (status IN ('done', 'partly_done') AND actual_minutes > 0))
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS study_sessions_date ON study_sessions(session_date)")
    if commit:
        connection.commit()


def checked_date(value=None):
    today = local_now().date()
    chosen = today if value is None else value
    if not isinstance(chosen, date) or chosen > today:
        raise SessionValidationError('Choose today or a past date.')
    return chosen, today


def occurs(activity, chosen):
    return is_activity_on_date(activity.activity_type, activity.date, activity.weekday,
                               chosen, activity.active_start_date, activity.active_end_date)


def _saved(connection, chosen):
    cursor = connection.execute("""SELECT activity_id, status, actual_minutes, name, subject,
        category, start_time, end_time, updated_at FROM study_sessions WHERE session_date = ?""",
        (chosen.isoformat(),))
    return {row[0]: dict(zip((column[0] for column in cursor.description), row)) for row in cursor}


def _item(activity_id, details, completion=None):
    return {'activity_id': activity_id,
            **{key: details[key] for key in ('name', 'subject', 'category', 'start_time', 'end_time')},
            'completion': ({key: completion[key] for key in ('status', 'actual_minutes', 'updated_at')}
                           if completion else None)}


def list_sessions(connection, session_date=None):
    chosen, today = checked_date(session_date)
    saved = _saved(connection, chosen)
    sessions = {activity.id: _item(activity.id, activity._asdict())
                for activity in get_all_activities(connection) if occurs(activity, chosen)}
    # Keep recorded history visible even if a definition was subsequently moved/edited.
    sessions.update({key: _item(key, record, record) for key, record in saved.items()})
    return {'date': chosen.isoformat(), 'today': today.isoformat(),
            'sessions': sorted(sessions.values(), key=lambda item:
                               (item['start_time'] or '99:99', item['name'].casefold(), item['activity_id']))}


def save_session(connection, activity_id, session_date, status, actual_minutes):
    chosen, _ = checked_date(session_date)
    if status not in {'done', 'partly_done', 'missed'}:
        raise SessionValidationError('Choose Done, Partly done, or Missed.')
    if type(actual_minutes) is not int or not 0 <= actual_minutes <= 1440:
        raise SessionValidationError('Actual minutes must be a whole number from 0 to 1440.')
    if (status == 'missed' and actual_minutes != 0) or (status != 'missed' and actual_minutes == 0):
        raise SessionValidationError('Use zero minutes for Missed and at least one minute for completed work.')
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        activity = next((item for item in get_all_activities(connection) if item.id == activity_id), None)
        if activity is None:
            raise SessionNotFoundError('Activity not found.')
        saved = _saved(connection, chosen).get(activity_id)
        if saved is None and not occurs(activity, chosen):
            raise SessionValidationError('This activity is not scheduled on that date.')
        details = saved or activity._asdict()
        updated_at = local_now().isoformat(timespec='seconds')
        connection.execute("""INSERT INTO study_sessions
            (activity_id, session_date, status, actual_minutes, name, subject, category,
             start_time, end_time, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id, session_date) DO UPDATE SET
                status = excluded.status, actual_minutes = excluded.actual_minutes,
                updated_at = excluded.updated_at""",
            (activity_id, chosen.isoformat(), status, actual_minutes,
             *(details[key] for key in ('name', 'subject', 'category', 'start_time', 'end_time')), updated_at))
    return {'status': status, 'actual_minutes': actual_minutes, 'updated_at': updated_at}


def clear_session(connection, activity_id, session_date):
    chosen, _ = checked_date(session_date)
    with connection:
        connection.execute('DELETE FROM study_sessions WHERE activity_id = ? AND session_date = ?',
                           (activity_id, chosen.isoformat()))
