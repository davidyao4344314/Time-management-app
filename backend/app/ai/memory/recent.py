"""Own each session\'s recent completed turns; archive successfully before eviction."""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock

from backend.app.ai.config import get_max_recent_turns
from backend.app.ai.memory import archive_store, selection

_sessions = {}
_lock = Lock()


def _archive_turn(session_id, turn):
    archive_store.append_archived_turn(session_id, turn)
    selection.report_archive_size()


def has_session(session_id):
    with _lock:
        return session_id in _sessions


def _archive_excess_turns(session_id, recent, limit):
    """Archive oldest turns before shrinking a session's recent window."""
    while len(recent) > limit:
        _archive_turn(session_id, recent[0])
        recent.popleft()


def enforce_recent_limit(session_id):
    """Explicit maintenance: archive successfully before shrinking the window."""
    limit = get_max_recent_turns()
    with _lock:
        recent = _sessions.get(session_id)
        if recent is not None:
            _archive_excess_turns(session_id, recent, limit)


def get_recent_turns(session_id):
    """Return a read-only snapshot; never archive or evict as a read side effect."""
    limit = get_max_recent_turns()
    with _lock:
        return deepcopy(list(_sessions.get(session_id, ()))[-limit:])


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
