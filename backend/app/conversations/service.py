"""Conversation operations; the trusted owner is supplied by the HTTP adapter."""
import sqlite3
import json
from uuid import UUID, uuid5
from contextlib import contextmanager

from backend.app import database
from backend.app.conversations import storage
from backend.app.conversations.context import build_chat_context
from backend.app.conversations.memory_context import retrieve_for_chat
from backend.app.conversations.memory_export import export_eligible_turns
from backend.app.conversations import summary
from backend.app.ai.agent.service import get_agent_proposal
from backend.app.ai.config import is_openai_api_key_configured
from backend.app.ai.agent.contracts import validate_agent_proposal
from backend.app.conversations.contracts import ConversationConflict
from backend.app.ai.memory import archive_store, recent


@contextmanager
def open_store():
    connection = sqlite3.connect(database.db_file, timeout=10)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        storage.migrate(connection)
        summary.migrate(connection)
        yield connection
    finally:
        connection.close()


def create_chat(owner_id, title=None):
    with open_store() as connection:
        return storage.create_conversation(connection, owner_id, title)


def list_chats(owner_id):
    with open_store() as connection:
        return storage.list_conversations(connection, owner_id)


def read_chat(owner_id, conversation_id, *, before=None, limit=50):
    with open_store() as connection:
        storage.require_conversation(connection,conversation_id,owner_id)
        storage.expire_interrupted_requests(connection,conversation_id)
        return {'conversation': storage.require_conversation(connection, conversation_id, owner_id),
                **storage.get_messages(connection, conversation_id, owner_id, before=before, limit=limit)}


def send_message(owner_id, conversation_id, request_id, message):
    with open_store() as connection:
        storage.require_conversation(connection, conversation_id, owner_id)
        storage.expire_interrupted_requests(connection,conversation_id)
        existing = storage.request_messages(connection, conversation_id, request_id)
        if not existing and not is_openai_api_key_configured():
            raise ConversationConflict('Configure the OpenAI API key first.')
        messages, created = storage.begin_request(connection, conversation_id, owner_id, request_id, message)
        if not created:
            return {'messages': messages, 'status': messages[0]['status']}
        try:
            context = build_chat_context(connection, conversation_id, owner_id)
            # Model observations use a separate read-only connection.
            observation_connection = sqlite3.connect(f'{database.db_file.resolve().as_uri()}?mode=ro', uri=True)
            try:
                proposal = get_agent_proposal(observation_connection, message, context['recent_turns'],
                    session_id=conversation_id, include_context=True, chat_summary=context['summary'],
                    memory_reader=lambda selected: retrieve_for_chat(connection, owner_id, conversation_id, selected,
                                                                   recent_turns=context['recent_turns']))
            finally:
                observation_connection.close()
            validate_agent_proposal({key:value for key,value in proposal.items() if key != 'agent_context'})
            messages = storage.complete_request(connection, conversation_id, request_id, proposal)
            try:
                export_eligible_turns(connection,owner_id,conversation_id)
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                # A memory export failure must not discard a saved assistant response.
                return {'messages':messages,'status':'completed','memory_export_pending':True}
            return {'messages': messages, 'status':'completed'}
        except Exception:
            storage.fail_request(connection, conversation_id, request_id)
            raise


def update_memory_sharing(owner_id, conversation_id, enabled):
    with open_store() as connection:
        chat = storage.set_memory_sharing(connection,conversation_id,owner_id,enabled)
        try:
            export_eligible_turns(connection,owner_id,conversation_id)
        except (OSError, ValueError, RuntimeError):
            chat['memory_export_pending'] = True
        return chat


def retry_memory_export(owner_id, conversation_id):
    with open_store() as connection:
        return export_eligible_turns(connection,owner_id,conversation_id)


def summarize_chat(owner_id,conversation_id):
    with open_store() as connection:
        return summary.update_summary(connection,conversation_id,owner_id)


def link_verified_legacy_chat(owner_id,legacy_id):
    """Called only after cookie verification. Never infer ownership from archive text."""
    if owner_id != legacy_id:
        return
    with open_store() as connection:
        row = connection.execute('SELECT owner_id FROM conversations WHERE conversation_id=?',(legacy_id,)).fetchone()
        if row:
            return
        turns = recent.get_recent_turns(legacy_id)
        has_archive = next(archive_store.iter_archive_records(session_id=legacy_id),None) is not None
        if not turns and not has_archive:
            return
        timestamp=storage.now_iso()
        with connection:
            connection.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',
                (legacy_id,owner_id,'Previous conversation',timestamp,timestamp,'active',0))
            sequence=0
            for index,turn in enumerate(turns):
                # Undated legacy turns are retained in the original store, not dated by guessing.
                if not turn.get('timestamp'):
                    continue
                proposal={key:value for key,value in turn['assistant'].items() if key!='agent_context'}
                from backend.app.infrastructure.privacy import redact_secrets
                proposal=redact_secrets(proposal)
                request=str(uuid5(UUID(legacy_id),f'legacy-{index}-{turn["timestamp"]}'))
                for role,content,saved in (('user',redact_secrets(turn['user']),None),('assistant',proposal['message'],json.dumps(proposal))):
                    sequence+=1
                    connection.execute('INSERT INTO conversation_messages VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (str(uuid5(UUID(request),role)),legacy_id,sequence,request,role,content,saved,None,'completed',turn['timestamp']))
