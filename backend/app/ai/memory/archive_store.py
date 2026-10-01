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


def iter_archived_turns():
    """Read valid JSONL archive records with their file positions."""
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
                    continue
                if isinstance(record, dict) and isinstance(record.get("turn"), dict):
                    yield position, record
        finally:
            fcntl.flock(archive.fileno(), fcntl.LOCK_UN)


def get_archive_turn_count():
    """Count valid archived turns across all sessions without changing the file."""
    return sum(1 for _ in iter_archived_turns())


def append_archived_turn(session_id, turn):
    """Append one JSON record, leaving all earlier archive records intact."""
    archived_turn = {key: value for key, value in turn.items() if key != "timestamp"}
    record = {
        "turn_id": str(uuid.uuid4()),
        "session_id": session_id,
        "turn": _redact_secrets(archived_turn),
    }
    if turn.get("timestamp") is not None:
        record["timestamp"] = turn["timestamp"]
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    with archive_write_lock():
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
