"""Read a few relevant turns from the existing per-session JSONL archive."""

import heapq
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.app.ai.memory import archive_store as ai_memory
from backend.app.infrastructure.privacy import redact_secrets
from backend.app.ai.memory.contracts import MemoryRequest, MemorySelection, ArchiveCategorySummary, SourceTurnReference
from backend.app.ai.memory.durable_store import read_durable_memories
from backend.app.ai.memory.records import source_identity
from backend.app.infrastructure.errors import MemoryUtilityError


LOCAL_TIMEZONE = ZoneInfo("Pacific/Auckland")
MAX_RESULTS = 5
MAX_TEXT_CHARS = 600
MAX_CONTEXT_CHARS = 8000


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

    terms = [term.casefold() for term in request.search_terms]
    best = []
    for position, record, timestamp, user, assistant, score in _raw_candidates(request, session_id, now):

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


def _raw_candidates(request, session_id, now, *, strict=False):
    start, end = resolve_time_reference(request.time_reference, now=now)
    terms = [term.casefold() for term in request.search_terms]

    records = (ai_memory.iter_archive_records(session_id=session_id, strict=True) if strict
               else ai_memory.iter_archived_turns(session_id=session_id))
    for position, record in records:
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

        yield position, record, timestamp, user, assistant, score


def _reference_ids(refs):
    return list(dict.fromkeys(
        ref.get("turn_id") or ref.get("record_sha256")
        for ref in refs if isinstance(ref, dict)
        and isinstance(ref.get("turn_id") or ref.get("record_sha256"), str)
    ))


def _memory_candidates(source, request, session_id, now):
    terms = [term.casefold() for term in request.search_terms]
    start, end = resolve_time_reference(request.time_reference, now=now)
    if source == "raw_archive":
        for _, record, timestamp, user, assistant, score in _raw_candidates(
            request, session_id, now, strict=True
        ):
            identity = source_identity(record)
            item_id = identity["turn_id"] or identity["record_sha256"]
            yield score, {
                "source": source, "id": item_id,
                "text": "User: " + _excerpt(user, terms) + "\nAssistant: " + _excerpt(assistant, terms),
                "timestamp": timestamp.isoformat() if timestamp else None,
                "precision": "conversation", "source_refs": [item_id],
            }
        return

    if source == "durable":
        records = read_durable_memories(session_id=session_id)
    else:
        records = (record for _, record in ai_memory.iter_archive_records(
            session_id=session_id, strict=True
        ) if record.get("record_type") == "compressed_summary")

    for record in records:
        refs = record.get("source_turn_refs", [])
        # Validate provenance before exposing identifiers as model context.
        for ref in refs:
            SourceTurnReference.model_validate({key: ref.get(key) for key in (
                "turn_id", "record_sha256", "session_id", "timestamp")})
        ref_ids = _reference_ids(refs)
        if source == "durable":
            timestamps = [_parse_timestamp(ref.get("timestamp")) for ref in refs]
            if start is not None and not any(t is not None and start <= t < end for t in timestamps):
                continue
            text = record["content"]
            keywords = record["type"]
            metadata = {"id": record["memory_id"], "timestamp": record["source_timestamp"],
                        "precision": "durable", "type": record["type"]}
        else:
            first = _parse_timestamp(record.get("period_start"))
            last = _parse_timestamp(record.get("period_end"))
            if first is not None and last is not None and first > last:
                continue
            if start is not None and (first is None or last is None or first >= end or last < start):
                continue
            categories = record.get("categories")
            if not isinstance(categories, dict) or not isinstance(record.get("summary_id"), str):
                raise ValueError("Invalid compressed summary.")
            uuid.UUID(record["summary_id"])
            validated = [ArchiveCategorySummary.model_validate(value) for value in categories.values()]
            text = " ".join(bullet for category in validated for bullet in category.summary)
            keywords = " ".join(word for category in validated for word in category.keywords)
            metadata = {"id": record["summary_id"], "period_start": first.isoformat() if first else None,
                        "period_end": last.isoformat() if last else None, "precision": "summary",
                        "time_match": "overlap_only" if start is not None else "not_filtered"}
        text = redact_secrets(text)
        searchable = (text + " " + keywords).casefold()
        score = sum(searchable.count(term) for term in terms)
        if not text.strip() or (terms and score == 0):
            continue
        yield score, {"source": source, **metadata, "text": _excerpt(text, terms),
                      "source_refs": ref_ids[:5], "source_ref_count": len(ref_ids)}


def search_memory(selection, *, session_id, now=None, authorized_sessions=None):
    """Read selected stores, rank/deduplicate, and cap the complete observation."""
    selected = MemorySelection.model_validate(selection)
    if not isinstance(session_id, str) or not session_id:
        return {"status": "unavailable", "items": [], "truncated": False,
                "unavailable_sources": selected.sources}
    candidates = []
    unavailable = []
    truncated = False
    priority = {"raw_archive": 3, "durable": 2, "compressed_archive": 1}
    sessions = list(dict.fromkeys(authorized_sessions)) if authorized_sessions is not None else [session_id]
    for source in selected.sources:
        try:
            # Retain only a small candidate pool, not the whole raw archive.
            pool = []
            def candidates_for_sessions():
                for identity in sessions:
                    for score, item in _memory_candidates(source, selected.query, identity, now):
                        if authorized_sessions is not None:
                            item = {**item, 'conversation_id': identity}
                        yield score, item
            for position, (score, item) in enumerate(candidates_for_sessions()):
                stamp = _parse_timestamp(item.get("timestamp") or item.get("period_end"))
                recency = stamp.timestamp() if stamp else float("-inf")
                ranked = (score, priority[source], recency, position, item)
                if len(pool) < MAX_RESULTS * 2:
                    heapq.heappush(pool, ranked)
                else:
                    truncated = True
                    if ranked[:4] > pool[0][:4]:
                        heapq.heapreplace(pool, ranked)
            candidates.extend(pool)
        except (OSError, UnicodeError, ValueError, RuntimeError, MemoryUtilityError):
            unavailable.append(source)

    items, seen_ids, seen_text = [], set(), set()
    for *_, item in sorted(candidates, key=lambda row: row[:4], reverse=True):
        identity = (item["source"], item["id"])
        normalized = (" ".join(item["text"].casefold().split()),
                      item.get("timestamp"), item.get("period_start"), item.get("period_end"))
        if identity in seen_ids or normalized in seen_text:
            continue
        refs = set(item["source_refs"])
        # Do not repeat the same underlying evidence from multiple stores.
        if refs and any(refs <= set(existing["source_refs"]) for existing in items):
            continue
        if len(items) >= MAX_RESULTS or len(json.dumps(items + [item], ensure_ascii=False)) > MAX_CONTEXT_CHARS - 300:
            truncated = True
            continue
        items.append(item)
        seen_ids.add(identity)
        seen_text.add(normalized)
    status = ("partial" if items else "unavailable") if unavailable else ("ok" if items else "empty")
    return {"status": status, "items": items, "truncated": truncated,
            "unavailable_sources": unavailable}
