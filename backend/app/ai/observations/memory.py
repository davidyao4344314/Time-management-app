"""A bounded read-only observation; no storage maintenance or model calls."""

from backend.app.ai.memory.search import search_memory


def build_memory_observation(selection, *, session_id, now=None):
    return search_memory(selection, session_id=session_id, now=now)
