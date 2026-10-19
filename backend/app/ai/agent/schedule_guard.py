"""Check proposal date coverage; no model calls, writes or approval authority."""

from datetime import date, timedelta

from backend.app.infrastructure.clock import local_now
from backend.app.planner.calendar import is_activity_on_date, is_valid_activity_time


def proposal_schedule_dates(proposal):
    """Resolve the bounded dates requiring timed scheduling evidence.

    One-time proposals check their exact dates. Daily/weekly proposals check
    their next seven dates using the existing recurrence predicate. This does
    not claim that an unrestricted recurring schedule is checked forever.
    """
    today = local_now().date()
    dates = set()
    for action in proposal.get("actions", []):
        if action["tool"] != "add_activity":
            continue
        fields = action["arguments"]
        if not is_valid_activity_time(fields["start_time"], fields["end_time"]):
            continue
        candidates = ([date.fromisoformat(fields["date"])] if fields["activity_type"] == "one_time"
                      else [today + timedelta(days=offset) for offset in range(7)])
        dates.update(day for day in candidates if is_activity_on_date(
            fields["activity_type"], fields["date"], fields["weekday"], day,
        ))
    return sorted(dates)


def unchecked_proposal_dates(proposal, observations):
    """Timed additions need fresh dated schedule evidence, not chat history."""
    dates = proposal_schedule_dates(proposal)
    activity = observations.get("activities")
    if not isinstance(activity, dict) or activity.get("status") == "unavailable":
        return sorted(dates)
    if "checked_dates" in activity:
        return sorted(day for day in dates if day.isoformat() not in activity["checked_dates"])
    period = activity.get("period") or {}
    try:
        first, last = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    except (KeyError, TypeError, ValueError):
        return sorted(dates)
    return sorted(day for day in dates if not first <= day <= last)
