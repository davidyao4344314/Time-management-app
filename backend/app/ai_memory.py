"""Recent completed AI turns, with older turns archived locally."""

import fcntl
import json
import logging
import os
import re
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.app.ai_config import get_max_recent_turns


ARCHIVE_FILE = Path(__file__).resolve().parents[1] / "ai_memory_archive.jsonl"
ARCHIVE_TURN_THRESHOLD = 100
ARCHIVE_COMPACT_BATCH = 50  # Reserved for a future compaction stage.
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
_sessions = {}
_lock = Lock()
_logger = logging.getLogger(__name__)


def get_archive_turn_count():
    """Count valid archived turns across all sessions without changing the file."""
    try:
        descriptor = os.open(
            ARCHIVE_FILE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
    except FileNotFoundError:
        return 0

    count = 0
    with os.fdopen(descriptor, "r", encoding="utf-8") as archive:
        fcntl.flock(archive.fileno(), fcntl.LOCK_SH)
        try:
            for line in archive:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and isinstance(record.get("turn"), dict):
                    count += 1
        finally:
            fcntl.flock(archive.fileno(), fcntl.LOCK_UN)
    return count


def archive_needs_compaction(archive_turn_count):
    """Report whether the archived-turn count exceeds the configured threshold."""
    return archive_turn_count > ARCHIVE_TURN_THRESHOLD


def _redact_secrets(value):
    """Avoid persisting an API key if one was pasted into a conversation."""
    if isinstance(value, str):
        value = _API_KEY_PATTERN.sub("[redacted API key]", value)
        configured_key = os.getenv("OPENAI_API_KEY", "").strip()
        if len(configured_key) >= 16:
            value = value.replace(configured_key, "[redacted API key]")
        return value
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secrets(item) for key, item in value.items()}
    return value


def _archive_turn(session_id, turn):
    """Append one JSON record, leaving all earlier archive records intact."""
    archived_turn = {key: value for key, value in turn.items() if key != "timestamp"}
    record = {"session_id": session_id, "turn": _redact_secrets(archived_turn)}
    if turn.get("timestamp") is not None:
        record["timestamp"] = turn["timestamp"]
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
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

    # This diagnostic must not fail a completed archive append: callers remove
    # the recent turn only after _archive_turn returns.
    try:
        archive_turn_count = get_archive_turn_count()
    except (OSError, UnicodeError):
        _logger.warning("Could not check the archive compaction threshold.")
    else:
        if archive_needs_compaction(archive_turn_count):
            _logger.warning(
                "Archive compaction required: %d archived turns.",
                archive_turn_count,
            )


def has_session(session_id):
    with _lock:
        return session_id in _sessions


def _archive_excess_turns(session_id, recent, limit):
    """Archive oldest turns before shrinking a session's recent window."""
    while len(recent) > limit:
        _archive_turn(session_id, recent[0])
        recent.popleft()


def get_recent_turns(session_id):
    """Return a copy so callers cannot alter stored conversation history."""
    limit = get_max_recent_turns()
    with _lock:
        recent = _sessions.get(session_id)
        if recent is None:
            return []
        _archive_excess_turns(session_id, recent, limit)
        return deepcopy(list(recent))


def add_completed_turn(session_id, user_message, proposal):
    """Keep the configured recent turns and archive older ones safely."""
    limit = get_max_recent_turns()
    turn = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": user_message,
        "assistant": deepcopy(proposal),
    }
    with _lock:
        recent = _sessions.setdefault(session_id, deque())
        _archive_excess_turns(session_id, recent, limit)
        if len(recent) == limit:
            _archive_turn(session_id, recent[0])
            recent.popleft()
        recent.append(turn)
