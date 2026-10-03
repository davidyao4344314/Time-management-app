"""Read bounded completed turns from one chat, independent of global memory."""
import json
from copy import deepcopy

from backend.app.ai.config import get_max_recent_turns
from backend.app.conversations import storage
from backend.app.conversations.storage import read_summary

MAX_RECENT_CONTEXT_CHARS = 16000
MAX_TURN_CONTEXT_CHARS = 8000


def _excerpt(text, limit):
    if len(text) <= limit:
        return text
    marker = '\n[Earlier/middle text omitted from context]\n'
    if limit <= len(marker):
        return text[:limit]
    remaining = max(0, limit - len(marker))
    return text[:remaining // 2] + marker + text[-(remaining - remaining // 2):]


def _bounded_turn(turn, budget):
    snapshot = deepcopy(turn)
    def size():
        return len(json.dumps({'user':snapshot['user'], 'assistant':snapshot['assistant']}, ensure_ascii=False))
    if size() <= budget:
        return snapshot, size()
    # Retain literal excerpts of both sides; never rewrite the stored transcript.
    snapshot['assistant']['actions'] = []
    snapshot['assistant']['message'] += '\n[Large turn excerpt; proposed action details may be omitted. No actions were executed.]'
    available = max(1, (budget - 400) // 2)
    while size() > budget:
        snapshot['user'] = _excerpt(snapshot['user'], available)
        snapshot['assistant']['message'] = _excerpt(snapshot['assistant']['message'], available)
        if size() > budget:
            # Other response metadata is not needed for conversation context.
            snapshot['assistant'] = {'message': snapshot['assistant']['message'], 'actions': []}
            available = max(1, available // 2)
    snapshot['context_truncated'] = True
    return snapshot, size()


def build_chat_context(connection, conversation_id, owner_id):
    turns = storage.completed_turns(connection, conversation_id, owner_id, limit=get_max_recent_turns())
    recent, size = [], 0
    for turn in reversed(turns):
        remaining = MAX_RECENT_CONTEXT_CHARS - size
        if remaining < 512:
            break
        snapshot, length = _bounded_turn(turn, min(remaining, MAX_TURN_CONTEXT_CHARS))
        recent.insert(0, snapshot)
        size += length
    summary = read_summary(connection,conversation_id)
    if summary and recent and summary['through_sequence_number'] >= recent[0]['sequence_number']:
        summary = None  # Increased recent window: don't send covered messages twice.
    return {'recent_turns': recent, 'summary': summary}
