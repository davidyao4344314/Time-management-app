"""Serialization, fingerprints, timestamps, and strict archive-record parsing.

These helpers operate only on supplied values; they do not read memory files.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from backend.app.infrastructure.errors import MemoryUtilityError


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def record_hash(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def source_identity(record):
    turn_id = record.get("turn_id")
    if turn_id is not None:
        if not isinstance(turn_id, str):
            raise MemoryUtilityError("A source turn ID is invalid.")
        try:
            uuid.UUID(turn_id)
        except ValueError as exc:
            raise MemoryUtilityError("A source turn ID is invalid.") from exc
        return {"turn_id": turn_id, "record_sha256": record_hash(record)}
    return {"turn_id": None, "record_sha256": record_hash(record)}


def archive_timestamp(record):
    """Return a comparable completion time, or None for an undated record."""
    value = record.get("timestamp") or record["turn"].get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.astimezone(timezone.utc)


def source_timestamp(record):
    """Preserve an existing timestamp string, including legacy turn-level ones."""
    value = record.get("timestamp") or record["turn"].get("timestamp")
    return value if isinstance(value, str) else None


def first_source_timestamp(refs):
    return next((ref["timestamp"] for ref in refs if ref["timestamp"] is not None), None)


def parse_archive_lines(data):
    """Preserve original lines and reject malformed data before replacing anything."""
    lines = data.splitlines(keepends=True)
    records = []
    for line_index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise MemoryUtilityError("The archive contains an invalid JSONL record.") from exc
        if not isinstance(record, dict) or ("turn" in record and not isinstance(record["turn"], dict)):
            raise MemoryUtilityError("The archive contains an invalid record.")
        records.append((line_index, record))
    return lines, records


def append_archive_record(data, record):
    separator = b"" if not data or data.endswith(b"\n") else b"\n"
    return data + separator + canonical_bytes(record) + b"\n"
