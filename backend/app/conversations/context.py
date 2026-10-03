"""Read bounded completed turns from one chat, independent of global memory."""
import json

from backend.app.ai.config import get_max_recent_turns
from backend.app.conversations import storage

MAX_RECENT_CONTEXT_CHARS = 16000


def build_chat_context(connection, conversation_id, owner_id):
    turns = storage.completed_turns(connection, conversation_id, owner_id, limit=get_max_recent_turns())
    recent, size = [], 0
    for turn in reversed(turns):
        length = len(json.dumps({'user':turn['user'],'assistant':turn['assistant']}, ensure_ascii=False))
        if size + length > MAX_RECENT_CONTEXT_CHARS:
            break  # Preserve a contiguous suffix of whole completed turns.
        recent.insert(0, turn)
        size += length
    return {'recent_turns': recent, 'summary': None}
