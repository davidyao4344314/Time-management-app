"""Retry-safe handoff of eligible completed chat turns to the existing archive."""
import json
from uuid import UUID, uuid5

from backend.app.ai.config import get_max_recent_turns
from backend.app.ai.memory import archive_store
from backend.app.ai.memory.selection import report_archive_size
from backend.app.conversations import storage


def migrate(connection):
    with connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS conversation_memory_exports(
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            request_id TEXT NOT NULL,
            turn_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','exported')),
            PRIMARY KEY(conversation_id,request_id)
        )''')


def export_eligible_turns(connection, owner_id, conversation_id):
    chat = storage.require_conversation(connection,conversation_id,owner_id)
    migrate(connection)
    if not chat['memory_sharing_enabled']:
        return {'exported':0}
    recent = storage.completed_turns(connection,conversation_id,owner_id,limit=get_max_recent_turns())
    cutoff = recent[0]['sequence_number'] if recent else 0
    rows = connection.execute('''SELECT u.content,a.proposal_json,a.created_at,u.request_id
        FROM conversation_messages u JOIN conversation_messages a
        ON u.conversation_id=a.conversation_id AND u.request_id=a.request_id
        WHERE u.conversation_id=? AND u.role='user' AND a.role='assistant'
        AND u.status='completed' AND a.status='completed' AND a.sequence_number < ?
        ORDER BY a.sequence_number''',(conversation_id,cutoff)).fetchall()
    exported = 0
    for user,proposal,timestamp,request_id in rows:
        identifier = str(uuid5(UUID(conversation_id),request_id))
        with connection:
            connection.execute('INSERT OR IGNORE INTO conversation_memory_exports(conversation_id,request_id,turn_id) VALUES(?,?,?)',
                               (conversation_id,request_id,identifier))
        status = connection.execute('SELECT status FROM conversation_memory_exports WHERE conversation_id=? AND request_id=?',
                                    (conversation_id,request_id)).fetchone()[0]
        if status == 'exported':
            continue
        archive_store.append_archived_turn(conversation_id,
            {'timestamp':timestamp,'user':user,'assistant':json.loads(proposal)},turn_id=identifier,owner_id=owner_id)
        # If the process stops before this receipt, the next append detects the stable ID.
        with connection:
            connection.execute("UPDATE conversation_memory_exports SET status='exported' WHERE conversation_id=? AND request_id=?",(conversation_id,request_id))
        exported += 1
    if exported:
        report_archive_size()
    return {'exported':exported}
