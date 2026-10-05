"""Factual coverage notices derived from observations, never from model claims."""

from datetime import date


MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _label(day):
    return f"{day.day} {MONTH_NAMES[day.month - 1]} {day.year}"


def exam_context_coverage(observation):
    """Return a compact scope notice only for a successfully observed period."""
    if not isinstance(observation, dict) or observation.get("status") == "unavailable":
        return None
    period = observation.get("period")
    if not isinstance(period, dict):
        return None
    try:
        first, last = (date.fromisoformat(period[key]) for key in ("start", "end"))
    except (KeyError, TypeError, ValueError):
        return None
    count, items = observation.get("count"), observation.get("upcoming")
    if first > last or type(count) is not int or count < 0 or not isinstance(items, list):
        return None
    formal_only = observation.get("assessment_filter") == "formal_exams"
    shown = len(items)
    truncated = observation.get("truncated") is True or shown < count
    unknown = observation.get("unknown_type_count", 0)
    if type(unknown) is not int or unknown < 0:
        unknown = 0
    label = "formal exams identified by explicit names" if formal_only else "assessments"
    notice = f"Context checked: {label}, {_label(first)}–{_label(last)}. Items outside this period are not included."
    if truncated:
        notice += f" Showing {shown} of {count} matching records; the detailed list is incomplete."
    if formal_only and unknown:
        notice += f" {unknown} ambiguously named assessment{'s were' if unknown != 1 else ' was'} not included as formal exams."
    return {"period": {"start": first.isoformat(), "end": last.isoformat()},
            "assessment_filter": "formal_exams" if formal_only else "all",
            "shown_count": shown, "matching_count": count,
            "truncated": truncated, "unknown_type_count": unknown,
            "notice": notice}


def add_exam_coverage_notice(proposal, coverage):
    """Append backend-verified scope without changing proposals or executing tools."""
    message = proposal.get("message")
    if coverage is None or not isinstance(message, str) or not message.strip():
        return proposal
    notice = coverage["notice"]
    if notice in message:
        return proposal
    return {**proposal, "message": f"{message.rstrip()}\n\n{notice}"}
