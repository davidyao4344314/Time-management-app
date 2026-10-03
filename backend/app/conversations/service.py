"""Conversation operations; the trusted owner is supplied by the HTTP adapter."""
import sqlite3
from contextlib import contextmanager

from backend.app import database
from backend.app.conversations import storage


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
