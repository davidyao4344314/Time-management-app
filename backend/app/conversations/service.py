"""Conversation operations; the trusted owner is supplied by the HTTP adapter."""
import sqlite3
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
from backend.app.conversations.legacy import link_legacy_chat
from backend.app.ai.context.adaptive import store as routing_store
from backend.app.ai.context.adaptive.settings import get_adaptive_settings
from backend.app.ai.context.adaptive.learning import make_completed_event, load_snapshot


@contextmanager
def open_store():
    connection = sqlite3.connect(database.db_file, timeout=10)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        storage.migrate(connection)
        summary.migrate(connection)
        routing_store.migrate(connection)
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
            adaptive_settings = get_adaptive_settings()
            routing_evidence = {} if adaptive_settings.mode != 'off' else None
            adaptive_snapshot = None
            if adaptive_settings.mode in {'shadow', 'active'}:
                try:
                    adaptive_snapshot = load_snapshot(connection, owner_id, conversation_id, adaptive_settings)
                except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                    pass  # Invalid/missing knowledge uses the original routing pipeline.
            # Model observations use a separate read-only connection.
            observation_connection = sqlite3.connect(f'{database.db_file.resolve().as_uri()}?mode=ro', uri=True)
            try:
                proposal = get_agent_proposal(observation_connection, message, context['recent_turns'],
                    session_id=conversation_id, include_context=True, chat_summary=context['summary'],
                    memory_reader=lambda selected: retrieve_for_chat(connection, owner_id, conversation_id, selected,
                                                                   recent_turns=context['recent_turns']),
                    **({'routing_evidence': routing_evidence} if routing_evidence is not None else {}),
                    **({'adaptive_snapshot': adaptive_snapshot} if adaptive_snapshot is not None else {}))
            finally:
                observation_connection.close()
            validate_agent_proposal({key:value for key,value in proposal.items() if key != 'agent_context'})
            messages = storage.complete_request(connection, conversation_id, request_id, proposal)
            learning_pending = False
            if routing_evidence is not None:
                try:
                    event = make_completed_event(owner_id, conversation_id, request_id, message, routing_evidence)
                    routing_store.record_event(connection, event.model_dump())
                except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                    learning_pending = True
            try:
                export_eligible_turns(connection,owner_id,conversation_id)
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                # A memory export failure must not discard a saved assistant response.
                return {'messages':messages,'status':'completed','memory_export_pending':True}
            return {'messages': messages, 'status':'completed',
                    **({'routing_learning_pending': True} if learning_pending else {})}
        except Exception:
            storage.fail_request(connection, conversation_id, request_id)
            raise


def update_memory_sharing(owner_id, conversation_id, enabled):
    with open_store() as connection:
        chat = storage.set_memory_sharing(connection,conversation_id,owner_id,enabled)
        try:
            export_eligible_turns(connection,owner_id,conversation_id)
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
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
        link_legacy_chat(connection, owner_id, legacy_id)
