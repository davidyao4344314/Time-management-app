"""Append/read raw archived turns; no recent sessions, selection or LLM calls."""

import fcntl
import json
import os
import uuid
from contextlib import contextmanager

from backend.app.infrastructure.atomic_files import exclusive_file_lock
from backend.app.infrastructure.privacy import _API_KEY_PATTERN, redact_secrets as _redact_secrets
from backend.app.ai.memory.paths import ARCHIVE_FILE


@contextmanager
def archive_write_lock():
    """Use the shared sidecar lock with the current archive-path override."""
    with exclusive_file_lock(ARCHIVE_FILE):
        yield


def iter_archive_records(*, session_id=None, strict=False):
    """Read a locked snapshot of records without changing archive contents.

    Session-scoped reads exclude legacy summaries with ambiguous ownership.
    Unscoped maintenance reads retain them; no historical data is discarded.
    """
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        raise ValueError("A nonempty session ID is required for a scoped read.")
    try:
        descriptor = os.open(
            ARCHIVE_FILE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
    except FileNotFoundError:
        return

    with os.fdopen(descriptor, "r", encoding="utf-8") as archive:
        fcntl.flock(archive.fileno(), fcntl.LOCK_SH)
        try:
            for position, line in enumerate(archive):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    if strict:
                        raise ValueError("Archive contains an invalid record.") from None
                    continue
                if not isinstance(record, dict):
                    continue
                if session_id is not None:
                    if record.get("record_type") == "compressed_summary":
                        refs = record.get("source_turn_refs")
                        if not isinstance(refs, list) or not refs or not all(
                            isinstance(ref, dict) and ref.get("session_id") == session_id
                            for ref in refs
                        ):
                            continue
                    elif record.get("session_id") != session_id:
                        continue
                yield position, record
        finally:
            fcntl.flock(archive.fileno(), fcntl.LOCK_UN)


def iter_archived_turns(*, session_id=None):
    """Read raw turns through the shared storage reader."""
    for position, record in iter_archive_records(session_id=session_id):
        if isinstance(record.get("turn"), dict):
            yield position, record


def get_archive_turn_count():
    """Count valid archived turns across all sessions without changing the file."""
    return sum(1 for _ in iter_archived_turns())


def append_archived_turn(session_id, turn, *, turn_id=None, owner_id=None):
    """Append one JSON record, leaving all earlier archive records intact."""
    archived_turn = {key: value for key, value in turn.items() if key != "timestamp"}
    record = {
        "turn_id": turn_id or str(uuid.uuid4()),
        "session_id": session_id,
        "turn": _redact_secrets(archived_turn),
    }
    if turn.get("timestamp") is not None:
        record["timestamp"] = turn["timestamp"]
    if owner_id is not None:
        record['owner_id'] = owner_id
        record['conversation_id'] = session_id
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    with archive_write_lock():
        if turn_id is not None:
            # Raw rows may already have been compacted; provenance still proves export.
            for _, existing in iter_archive_records(strict=True):
                if existing.get('turn_id') == turn_id or any(
                    ref.get('turn_id') == turn_id for ref in existing.get('source_turn_refs', []) if isinstance(ref,dict)):
                    return False
        descriptor = os.open(ARCHIVE_FILE, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.fchmod(descriptor, 0o600)
            remaining = data
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("Could not append the archived conversation turn.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
    return True
