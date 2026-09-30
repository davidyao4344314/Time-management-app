"""Recent completed AI turns, with older turns archived locally."""

import fcntl
import json
import os
import re
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


MAX_TURNS = 5
ARCHIVE_FILE = Path(__file__).resolve().parents[1] / "ai_memory_archive.jsonl"
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
_sessions = {}
_lock = Lock()


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


def has_session(session_id):
    with _lock:
        return session_id in _sessions


def get_recent_turns(session_id):
    """Return a copy so callers cannot alter stored conversation history."""
    with _lock:
        return deepcopy(list(_sessions.get(session_id, ())))


def add_completed_turn(session_id, user_message, proposal):
    """Keep five recent turns and archive the oldest before it leaves memory."""
    turn = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": user_message,
        "assistant": deepcopy(proposal),
    }
    with _lock:
        recent = _sessions.setdefault(session_id, deque(maxlen=MAX_TURNS))
        if len(recent) == MAX_TURNS:
            _archive_turn(session_id, recent[0])
            recent.popleft()
        recent.append(turn)
