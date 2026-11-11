"""Bounded, read-only completion history from the same records as Home."""

import re
from datetime import date, timedelta

from backend.app.infrastructure.clock import local_now
from backend.app.planner.study_sessions import list_sessions
from backend.app.ai.observations.formatting import bounded_details

MAX_HISTORY_DAYS = 31


def history_period(message, today):
    """Resolve history dates separately from the forward calendar window."""
    text = message.casefold()
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
    if dates and not re.search(r'\b(?:yesterday|last week|last month|this week|this month|(?:last|past) \d+ days?)\b', text):
        requested_first, requested_last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        if requested_first > requested_last:
            raise ValueError('The history dates are reversed.')
    elif 'yesterday' in text:
        requested_first = requested_last = today - timedelta(days=1)
    elif 'last week' in text:
        requested_last = today - timedelta(days=today.weekday() + 1)
        requested_first = requested_last - timedelta(days=6)
    elif 'last month' in text:
        requested_last = today.replace(day=1) - timedelta(days=1)
        requested_first = requested_last.replace(day=1)
    elif match := re.search(r'\b(?:last|past) (\d{1,4}) days?\b', text):
        days = int(match[1])
        if days < 1:
            raise ValueError('Choose at least one history day.')
        requested_first, requested_last = today - timedelta(days=days - 1), today
    elif 'this week' in text:
        requested_first, requested_last = today - timedelta(days=today.weekday()), today
    elif 'this month' in text:
        requested_first, requested_last = today.replace(day=1), today
    elif re.search(r'\b(today|tonight)\b', text):
        requested_first = requested_last = today
    else:
        requested_first, requested_last = today - timedelta(days=6), today
    last = min(requested_last, today)
    if requested_first > last:
        raise ValueError('Completion history cannot cover future dates.')
    first = max(requested_first, last - timedelta(days=MAX_HISTORY_DAYS - 1))
    return first, last, first != requested_first or last != requested_last


def build_study_session_observation(connection, user_request=''):
    today = local_now().date()
    first, last, period_limited = history_period(user_request, today)
    sessions = []
    for offset in range((last - first).days + 1):
        chosen = first + timedelta(days=offset)
        for item in list_sessions(connection, chosen)['sessions']:
            completion = item['completion']
            sessions.append({
                'activity_id': item['activity_id'], 'date': chosen.isoformat(),
                **{key: item[key] for key in ('name', 'subject', 'category', 'start_time', 'end_time')},
                'status': completion['status'] if completion else 'unrecorded',
                'actual_minutes': completion['actual_minutes'] if completion else None,
                'automatic': bool(completion and completion['automatic']),
            })
    counts = {status: 0 for status in ('done', 'partly_done', 'missed', 'unrecorded')}
    recorded_count, automatic_count, minutes = 0, 0, 0
    subjects = {}
    for item in sessions:
        counts[item['status']] += 1
        automatic_count += item['automatic']
        recorded_count += item['status'] != 'unrecorded' and not item['automatic']
        minutes += item['actual_minutes'] or 0
        key = (item['subject'], item['category'])
        group = subjects.setdefault(key, {'subject': key[0], 'category': key[1], 'count': 0, 'actual_minutes': 0})
        group['count'] += 1
        group['actual_minutes'] += item['actual_minutes'] or 0
    sessions.sort(key=lambda item: (item['date'], item['start_time'] or '', item['activity_id']), reverse=True)
    details = bounded_details(sessions)
    groups = bounded_details(subjects.values())
    return {'status': 'provided' if sessions else 'empty',
            'period': {'start': first.isoformat(), 'end': last.isoformat()},
            'period_limited': period_limited, 'count': len(sessions), 'counts': counts,
            'recorded_count': recorded_count, 'automatic_missed_count': automatic_count,
            'actual_minutes': minutes, 'sessions': details, 'truncated': len(details) < len(sessions),
            'by_subject_category': groups, 'subject_totals_truncated': len(groups) < len(subjects),
            'coverage': 'Only the stated period is covered. All activity categories are included; do not treat them all as study. '
                        'Automatic missed means no outcome was recorded for a past scheduled date, not verified nonattendance. '
                        'Unrecorded minutes are unknown. Historical unlogged recurrences follow current activity definitions; '
                        'explicitly recorded sessions retain saved details. Totals cover the full stated period even when details are truncated.'}
