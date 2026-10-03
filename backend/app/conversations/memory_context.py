"""Authorize memory scopes before read-only retrieval, reusing existing budgets."""
import heapq
import json
from uuid import UUID, uuid5

from backend.app.conversations import storage
from backend.app.ai.memory.contracts import MemorySelection
from backend.app.ai.memory.search import search_memory, resolve_time_reference, MAX_RESULTS, MAX_CONTEXT_CHARS
from backend.app.ai.memory.search_helpers import parse_timestamp as _parse_timestamp, excerpt as _excerpt, keyword_score
from backend.app.infrastructure.privacy import redact_secrets


def local_history(connection, conversation_id, owner_id, selection, *, recent_turns=()):
    storage.require_conversation(connection, conversation_id, owner_id)
    selected = MemorySelection.model_validate(selection)
    start, end = resolve_time_reference(selected.query.time_reference)
    terms = [term.casefold() for term in selected.query.search_terms]
    pool = []
    excluded = {turn.get('request_id') for turn in recent_turns}
    rows = storage.history_rows(connection, conversation_id, owner_id)
    matches = 0
    for index, (user, assistant, timestamp, message_id, request_id) in enumerate(rows):
        if request_id in excluded:
            continue
        stamp = _parse_timestamp(timestamp)
        if start is not None and (stamp is None or not start <= stamp < end):
            continue
        text = redact_secrets(f'User: {user}\nAssistant: {assistant}')
        score = keyword_score((text,), terms)
        if terms and score == 0:
            continue
        matches += 1
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
    return {'status':'ok' if items else 'empty','items':items,'truncated':len(items)<matches,'unavailable_sources':[]}


def retrieve_for_chat(connection, owner_id, conversation_id, selection, *, recent_turns=()):
    storage.require_conversation(connection, conversation_id, owner_id)
    selected = MemorySelection.model_validate(selection)
    if selected.scope == 'current_chat':
        result = local_history(connection, conversation_id, owner_id, selection, recent_turns=recent_turns)
    else:
        authorized = storage.shared_conversation_ids(connection, owner_id)
        result = search_memory(selection, session_id=conversation_id, authorized_sessions=authorized)
    excluded = set()
    for turn in recent_turns:
        if turn.get('request_id'):
            excluded.add(str(uuid5(UUID(conversation_id), turn['request_id'])))
    result['items'] = [item for item in result['items'] if not (
        item.get('source_refs') and set(item['source_refs']) <= excluded
        and item.get('source_ref_count', len(item['source_refs'])) == len(item['source_refs']))]
    result['items'] = [item for item in result['items'] if not any(
        turn['user'] in item['text'] and turn['assistant']['message'] in item['text'] for turn in recent_turns)]
    if not result['items'] and result['status'] == 'ok':
        result['status'] = 'empty'
    result['scope'] = 'current_chat' if selected.scope == 'current_chat' else 'global'
    return result
