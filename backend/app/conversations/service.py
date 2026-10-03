"""Conversation operations; the trusted owner is supplied by the HTTP adapter."""
import sqlite3
from contextlib import contextmanager

from backend.app import database
from backend.app.conversations import storage
from backend.app.conversations.context import build_chat_context
from backend.app.conversations.memory_context import retrieve_for_chat
from backend.app.ai.agent.service import get_agent_proposal
from backend.app.ai.config import is_openai_api_key_configured
from backend.app.ai.agent.contracts import validate_agent_proposal
from backend.app.conversations.contracts import ConversationConflict


@contextmanager
def open_store():
    connection = sqlite3.connect(database.db_file, timeout=10)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        storage.migrate(connection)
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
        return {'conversation': storage.require_conversation(connection, conversation_id, owner_id),
                **storage.get_messages(connection, conversation_id, owner_id, before=before, limit=limit)}


def send_message(owner_id, conversation_id, request_id, message):
    with open_store() as connection:
        storage.require_conversation(connection, conversation_id, owner_id)
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
                    session_id=conversation_id, include_context=True,
                    memory_reader=lambda selected: retrieve_for_chat(connection, owner_id, conversation_id, selected,
                                                                   recent_turns=context['recent_turns']))
            finally:
                observation_connection.close()
            validate_agent_proposal({key:value for key,value in proposal.items() if key != 'agent_context'})
            messages = storage.complete_request(connection, conversation_id, request_id, proposal)
            return {'messages': messages, 'status':'completed'}
        except Exception:
            storage.fail_request(connection, conversation_id, request_id)
            raise
