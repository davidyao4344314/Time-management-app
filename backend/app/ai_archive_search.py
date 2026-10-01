"""Read a few relevant turns from the existing per-session JSONL archive."""

import heapq
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.app import ai_memory
from backend.app.infrastructure.privacy import redact_secrets
from backend.app.memory.contracts import MemoryRequest


LOCAL_TIMEZONE = ZoneInfo("Pacific/Auckland")
MAX_RESULTS = 5
MAX_TEXT_CHARS = 600


def _next_month(first_day):
    if first_day.month == 12:
        return date(first_day.year + 1, 1, 1)
    return date(first_day.year, first_day.month + 1, 1)


def resolve_time_reference(time_reference, *, now=None):
    """Return a half-open local datetime range, or (None, None) for no range."""
    if time_reference in (None, "unspecified"):
        return None, None

    now = now or datetime.now(LOCAL_TIMEZONE)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone.")
    today = now.astimezone(LOCAL_TIMEZONE).date()

    if time_reference == "today":
        start, end = today, today + timedelta(days=1)
    elif time_reference == "yesterday":
        start, end = today - timedelta(days=1), today
    elif time_reference in ("this_week", "last_week"):
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday if time_reference == "this_week" else this_monday - timedelta(days=7)
        end = start + timedelta(days=7)
    elif time_reference in ("this_month", "last_month"):
        this_month = today.replace(day=1)
        start = this_month if time_reference == "this_month" else (this_month - timedelta(days=1)).replace(day=1)
        end = _next_month(this_month) if time_reference == "this_month" else this_month
    else:
        raise ValueError("Unknown memory time reference.")

    return (
        datetime.combine(start, time.min, tzinfo=LOCAL_TIMEZONE),
        datetime.combine(end, time.min, tzinfo=LOCAL_TIMEZONE),
    )


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp


def _excerpt(text, terms):
    """Keep the matched topic in a short, literal excerpt when text is long."""
    if len(text) <= MAX_TEXT_CHARS:
        return text
    folded = text.casefold()
    positions = [folded.find(term.casefold()) for term in terms]
    matches = [position for position in positions if position >= 0]
    start = max(0, min(matches) - 100) if matches else 0
    start = min(start, len(text) - MAX_TEXT_CHARS)
    end = start + MAX_TEXT_CHARS
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def search_archived_memory(memory_request, *, session_id, limit=5, now=None):
    """Search only one session's archive and return at most five ranked turns.

    Undated legacy records can match topic-only searches, but cannot be placed
    in a time range. The caller, not the model, must supply the session ID.
    """
    request = MemoryRequest.model_validate(memory_request)
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("A browser session ID is required for archive search.")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer.")
    count = min(limit, MAX_RESULTS)
    if count == 0:
        return {"retrieved_archive": []}

    start, end = resolve_time_reference(request.time_reference, now=now)
    terms = [term.casefold() for term in request.search_terms]
    best = []

    try:
        descriptor = os.open(
            ai_memory.ARCHIVE_FILE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
    except FileNotFoundError:
        return {"retrieved_archive": []}

    with os.fdopen(descriptor, "r", encoding="utf-8") as archive:
        for position, line in enumerate(archive):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("session_id") != session_id:
                continue
            turn = record.get("turn")
            if not isinstance(turn, dict):
                continue
            user = turn.get("user")
            assistant = turn.get("assistant")
            if isinstance(assistant, dict):
                assistant = assistant.get("message")
            if not isinstance(user, str) or not isinstance(assistant, str):
                continue

            timestamp = _parse_timestamp(record.get("timestamp") or turn.get("timestamp"))
            if start is not None and (timestamp is None or not start <= timestamp < end):
                continue

            user = redact_secrets(user)
            assistant = redact_secrets(assistant)
            user_text, assistant_text = user.casefold(), assistant.casefold()
            score = sum(2 * user_text.count(term) + assistant_text.count(term) for term in terms)
            if terms and score == 0:
                continue

            result = {
                "timestamp": timestamp.isoformat() if timestamp is not None else None,
                "user": _excerpt(user, terms),
                "assistant": _excerpt(assistant, terms),
            }
            recency = timestamp.astimezone(timezone.utc) if timestamp is not None \
                else datetime.min.replace(tzinfo=timezone.utc)
            ranked = (score, recency, position, result)
            if len(best) < count:
                heapq.heappush(best, ranked)
            elif ranked[:3] > best[0][:3]:
                heapq.heapreplace(best, ranked)

    best.sort(key=lambda item: item[:3], reverse=True)
    return {"retrieved_archive": [item[3] for item in best]}
