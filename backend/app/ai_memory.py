"""Temporary, per-session history of completed AI proposal turns."""

from collections import deque
from copy import deepcopy
from threading import Lock


MAX_TURNS = 5
_sessions = {}
_lock = Lock()


def has_session(session_id):
    with _lock:
        return session_id in _sessions


def get_recent_turns(session_id):
    """Return a copy so callers cannot alter stored conversation history."""
    with _lock:
        return deepcopy(list(_sessions.get(session_id, ())))


def add_completed_turn(session_id, user_message, proposal):
    """Remember only a successful response; deque drops the oldest after five."""
    turn = {"user": user_message, "assistant": deepcopy(proposal)}
    with _lock:
        _sessions.setdefault(session_id, deque(maxlen=MAX_TURNS)).append(turn)
