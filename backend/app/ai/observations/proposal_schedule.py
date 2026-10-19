"""Fresh bounded calendar evidence for proposed dates, never historical memory."""

from datetime import date

from backend.app.ai.actions.contracts import MAX_ADD_ACTIVITY_PROPOSALS
from backend.app.ai.observations.activities import _occurrences_in_range, _busy_ranges, _brief_occurrence
from backend.app.ai.observations.formatting import bounded_details


def build_proposal_schedule_observation(connection, dates):
    """Read exact proposed dates using existing calendar recurrence logic.

    At most ten one-time dates plus seven near-term recurring dates. A sparse
    list does not claim coverage of the intervening dates. Busy intervals are
    complete for checked dates even when descriptive detail is truncated.
    """
    if (not dates or len(dates) > MAX_ADD_ACTIVITY_PROPOSALS + 7
            or any(type(day) is not date for day in dates)):
        raise ValueError("Choose a bounded set of proposed calendar dates.")
    dates = sorted(set(dates))
    occurrences = [item for day in dates for item in _occurrences_in_range(connection, day, day)]
    busy, untimed = _busy_ranges(occurrences)
    detail = bounded_details(_brief_occurrence(item, include_date=True) for item in occurrences)
    return {"checked_dates": [day.isoformat() for day in dates], "busy": busy,
            "count": len(occurrences), "untimed_count": untimed,
            "upcoming_7d": detail, "truncated": len(detail) < len(occurrences)}
