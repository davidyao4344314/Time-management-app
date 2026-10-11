"""Durable owner-scoped proposals and receipts in the existing SQLite database."""
import json
from datetime import datetime, timezone

from backend.app.ai.actions.contracts import ActionProposal


def migrate(connection):
    with connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS action_proposals (
            proposal_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            conversation_id TEXT,
            request_id TEXT,
            proposal_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending_approval','rejected','completed','failed')),
            result_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
        )''')
        connection.execute('CREATE INDEX IF NOT EXISTS actions_owner ON action_proposals(owner_id, created_at)')
        connection.execute('CREATE INDEX IF NOT EXISTS actions_origin ON action_proposals(conversation_id, request_id)')


def insert_proposals(connection, owner, proposals, *, conversation_id=None, request_id=None):
    """Caller owns the transaction: chat completion and authority are one write."""
    for proposal in proposals:
        validated = ActionProposal.model_validate(proposal.model_dump(), strict=True)
        if validated.status.value != 'pending_approval':
            raise ValueError('Only pending proposals can be registered.')
        if validated.tool_name in {'edit_activity', 'delete_activity'} and validated.target_snapshot is None:
            raise ValueError('Activity mutations require a trusted review snapshot.')
        connection.execute('INSERT INTO action_proposals VALUES(?,?,?,?,?,?,?,?)',
            (validated.id, owner, conversation_id, request_id, validated.model_dump_json(),
             'pending_approval', None, datetime.now(timezone.utc).isoformat()))


def read_proposal(connection, owner, identifier):
    return connection.execute('''SELECT proposal_json,status,result_json,conversation_id,request_id FROM action_proposals
        WHERE owner_id=? AND proposal_id=?''', (owner, identifier)).fetchone()


def public_view(identifier, row):
    proposal = json.loads(row[0])
    return {'id': identifier, 'display_title': proposal['display_title'],
            'display_description': proposal['display_description'], 'status': row[1],
            'requires_approval': True, 'result': json.loads(row[2]) if row[2] else None,
            'conversation_id': row[3], 'request_id': row[4]}


def finish(connection, owner, identifier, status, result=None):
    connection.execute('UPDATE action_proposals SET status=?,result_json=? WHERE owner_id=? AND proposal_id=?',
        (status, result.model_dump_json() if result else None, owner, identifier))
