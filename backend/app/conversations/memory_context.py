"""Authorize memory scopes before read-only retrieval, reusing existing budgets."""
import heapq
import json

from backend.app.conversations import storage
from backend.app.ai.memory.contracts import MemorySelection
from backend.app.ai.memory.search import search_memory, resolve_time_reference, _parse_timestamp, _excerpt, MAX_RESULTS, MAX_CONTEXT_CHARS
from backend.app.infrastructure.privacy import redact_secrets


def local_history(connection, conversation_id, owner_id, selection):
    storage.require_conversation(connection, conversation_id, owner_id)
    selected = MemorySelection.model_validate(selection)
    start, end = resolve_time_reference(selected.query.time_reference)
    terms = [term.casefold() for term in selected.query.search_terms]
    pool = []
    rows = connection.execute('''SELECT u.content,a.content,a.created_at,a.message_id
        FROM conversation_messages u JOIN conversation_messages a
        ON u.conversation_id=a.conversation_id AND u.request_id=a.request_id
        WHERE u.conversation_id=? AND u.role='user' AND a.role='assistant'
        AND u.status='completed' AND a.status='completed' ''', (conversation_id,))
    for index, (user, assistant, timestamp, message_id) in enumerate(rows):
        stamp = _parse_timestamp(timestamp)
        if start is not None and (stamp is None or not start <= stamp < end):
            continue
        text = redact_secrets(f'User: {user}\nAssistant: {assistant}')
        score = sum(text.casefold().count(term) for term in terms)
        if terms and score == 0:
            continue
        item = {'source':'current_chat', 'id':message_id, 'text':_excerpt(text,terms),
                'timestamp':timestamp, 'precision':'conversation', 'source_refs':[message_id],
                'conversation_id':conversation_id}
        ranked = (score,timestamp,index,item)
        if len(pool) < MAX_RESULTS:
            heapq.heappush(pool,ranked)
        elif ranked[:3] > pool[0][:3]:
            heapq.heapreplace(pool,ranked)
    items = []
    for *_, item in sorted(pool,reverse=True):
        if len(json.dumps(items+[item],ensure_ascii=False)) < MAX_CONTEXT_CHARS-300:
            items.append(item)
    return {'status':'ok' if items else 'empty','items':items,'truncated':len(items)<len(pool),'unavailable_sources':[]}


def retrieve_for_chat(connection, owner_id, conversation_id, selection, *, recent_turns=()):
    storage.require_conversation(connection, conversation_id, owner_id)
    selected = MemorySelection.model_validate(selection)
    if selected.scope == 'current_chat':
        result = local_history(connection, conversation_id, owner_id, selection)
    else:
        authorized = [row[0] for row in connection.execute('''SELECT conversation_id FROM conversations
            WHERE owner_id=? AND memory_sharing_enabled=1''', (owner_id,))]
        result = search_memory(selection, session_id=conversation_id, authorized_sessions=authorized)
    result['items'] = [item for item in result['items'] if not any(
        turn['user'] in item['text'] and turn['assistant']['message'] in item['text'] for turn in recent_turns)]
    if not result['items'] and result['status'] == 'ok':
        result['status'] = 'empty'
    result['scope'] = 'current_chat' if selected.scope == 'current_chat' else 'global'
    return result
