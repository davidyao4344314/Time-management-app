"""SQLite chat storage. No agent calls, archive access or HTTP dependencies."""

import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from backend.app.conversations.contracts import ConversationConflict, ConversationNotFound
from backend.app.infrastructure.privacy import redact_secrets


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def migrate(connection):
    """Add tables without replacing any existing application data."""
    with connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS conversations(
            conversation_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
            memory_sharing_enabled INTEGER NOT NULL DEFAULT 0
                CHECK(memory_sharing_enabled IN (0,1))
        )''')
        connection.execute('''CREATE TABLE IF NOT EXISTS conversation_messages(
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            sequence_number INTEGER NOT NULL,
            request_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            proposal_json TEXT,
            inspector_json TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')),
            created_at TEXT NOT NULL,
            UNIQUE(conversation_id, sequence_number),
            UNIQUE(conversation_id, request_id, role)
        )''')
        connection.execute('CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(owner_id, updated_at)')
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS conversation_pending ON conversation_messages(conversation_id) WHERE role='user' AND status='pending'")


def _conversation(row):
    keys = ('conversation_id', 'owner_id', 'title', 'created_at', 'updated_at', 'status', 'memory_sharing_enabled')
    item = dict(zip(keys, row))
    item['memory_sharing_enabled'] = bool(item['memory_sharing_enabled'])
    return item


def require_conversation(connection, conversation_id, owner_id):
    row = connection.execute('SELECT * FROM conversations WHERE conversation_id=? AND owner_id=?',
                             (conversation_id, owner_id)).fetchone()
    if row is None:
        raise ConversationNotFound('Conversation not found.')
    return _conversation(row)


def create_conversation(connection, owner_id, title=None):
    identifier, timestamp = uuid4().hex, now_iso()
    with connection:
        connection.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',
                           (identifier, owner_id, redact_secrets(title), timestamp, timestamp, 'active', 0))
    return require_conversation(connection, identifier, owner_id)


def list_conversations(connection, owner_id):
    return [_conversation(row) for row in connection.execute(
        'SELECT * FROM conversations WHERE owner_id=? ORDER BY updated_at DESC, conversation_id LIMIT 100', (owner_id,))]


def message_dict(row):
    item = dict(zip(('message_id','conversation_id','sequence_number','request_id','role','content',
                     'proposal_json','inspector_json','status','created_at'), row))
    proposal = json.loads(item.pop('proposal_json')) if item['proposal_json'] else None
    inspector = json.loads(item.pop('inspector_json')) if item['inspector_json'] else None
    if proposal is not None:
        item['proposal'] = proposal
    if inspector is not None:
        item['agent_context'] = inspector
    return item


def get_messages(connection, conversation_id, owner_id, *, before=None, limit=50):
    require_conversation(connection, conversation_id, owner_id)
    limit = max(1, min(limit, 100))
    rows = list(connection.execute('''SELECT * FROM conversation_messages
        WHERE conversation_id=? AND sequence_number < ?
        ORDER BY sequence_number DESC LIMIT ?''', (conversation_id, before or 2**63-1, limit+1)))
    has_more = len(rows) > limit
    items = [message_dict(row) for row in reversed(rows[:limit])]
    return {'messages': items, 'has_more': has_more,
            'next_before': items[0]['sequence_number'] if has_more else None}


def request_messages(connection, conversation_id, request_id):
    return [message_dict(row) for row in connection.execute(
        'SELECT * FROM conversation_messages WHERE conversation_id=? AND request_id=? ORDER BY sequence_number',
        (conversation_id, request_id))]


def begin_request(connection, conversation_id, owner_id, request_id, content):
    """Reserve one turn in a short transaction, with retry/conflict protection."""
    connection.execute('BEGIN IMMEDIATE')
    try:
        chat = require_conversation(connection, conversation_id, owner_id)
        existing = request_messages(connection, conversation_id, request_id)
        if existing:
            if existing[0]['content'] != redact_secrets(content):
                raise ConversationConflict('This request ID belongs to a different message.')
            connection.commit()
            return existing, False
        if chat['status'] != 'active':
            raise ConversationConflict('This conversation is archived.')
        if connection.execute("SELECT 1 FROM conversation_messages WHERE conversation_id=? AND status='pending'", (conversation_id,)).fetchone():
            raise ConversationConflict('A request is already running in this chat.')
        sequence = connection.execute('SELECT COALESCE(MAX(sequence_number),0)+1 FROM conversation_messages WHERE conversation_id=?', (conversation_id,)).fetchone()[0]
        timestamp = now_iso()
        connection.execute('INSERT INTO conversation_messages VALUES(?,?,?,?,?,?,?,?,?,?)',
            (str(uuid4()), conversation_id, sequence, request_id, 'user', redact_secrets(content), None, None, 'pending', timestamp))
        connection.execute('UPDATE conversations SET updated_at=?, title=COALESCE(title,?) WHERE conversation_id=?',
                           (timestamp, redact_secrets(content[:80]), conversation_id))
        connection.commit()
        return request_messages(connection, conversation_id, request_id), True
    except Exception:
        connection.rollback()
        raise


def complete_request(connection, conversation_id, request_id, proposal):
    """Persist the response and user completion atomically, retaining IDs."""
    with connection:
        rows = request_messages(connection, conversation_id, request_id)
        if not rows or rows[0]['status'] != 'pending':
            raise ConversationConflict('The request is no longer pending.')
        clean = redact_secrets({key: value for key, value in proposal.items() if key != 'agent_context'})
        inspector = redact_secrets(proposal.get('agent_context'))
        connection.execute('INSERT INTO conversation_messages VALUES(?,?,?,?,?,?,?,?,?,?)',
            (str(uuid4()), conversation_id, rows[0]['sequence_number']+1, request_id, 'assistant',
             clean['message'], json.dumps(clean), json.dumps(inspector) if inspector else None, 'completed', now_iso()))
        connection.execute("UPDATE conversation_messages SET status='completed' WHERE conversation_id=? AND request_id=? AND role='user'", (conversation_id, request_id))
        connection.execute('UPDATE conversations SET updated_at=? WHERE conversation_id=?', (now_iso(), conversation_id))
    return request_messages(connection, conversation_id, request_id)


def fail_request(connection, conversation_id, request_id):
    with connection:
        connection.execute("UPDATE conversation_messages SET status='failed' WHERE conversation_id=? AND request_id=? AND status='pending'", (conversation_id, request_id))


def expire_interrupted_requests(connection, conversation_id):
    """Maintenance before reads/sends; never retry a paid request automatically."""
    cutoff = (datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat(timespec='seconds')
    with connection:
        connection.execute("UPDATE conversation_messages SET status='failed' WHERE conversation_id=? AND status='pending' AND created_at<?",
                           (conversation_id,cutoff))


def completed_turns(connection, conversation_id, owner_id, *, limit=100):
    require_conversation(connection, conversation_id, owner_id)
    rows = list(connection.execute('''SELECT u.content,a.proposal_json,a.sequence_number,a.created_at,u.request_id
        FROM conversation_messages u JOIN conversation_messages a
        ON u.conversation_id=a.conversation_id AND u.request_id=a.request_id
        WHERE u.conversation_id=? AND u.role='user' AND a.role='assistant'
        AND u.status='completed' AND a.status='completed'
        ORDER BY a.sequence_number DESC LIMIT ?''', (conversation_id, max(1,min(limit,100)))))
    return [{'user': row[0], 'assistant': json.loads(row[1]), 'sequence_number': row[2],
             'timestamp': row[3], 'request_id': row[4]} for row in reversed(rows)]


def set_memory_sharing(connection, conversation_id, owner_id, enabled):
    require_conversation(connection, conversation_id, owner_id)
    with connection:
        connection.execute('UPDATE conversations SET memory_sharing_enabled=? WHERE conversation_id=?', (int(enabled),conversation_id))
    return require_conversation(connection, conversation_id, owner_id)
