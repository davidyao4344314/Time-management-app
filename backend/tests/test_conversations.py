"""Persistent conversation behavior in disposable databases; no model calls."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.app.conversations import storage
from backend.app.conversations.contracts import ConversationConflict, ConversationNotFound


class ConversationStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'chat.db'
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.connection.close())
        self.connection.execute('PRAGMA foreign_keys=ON')
        storage.migrate(self.connection)
        self.chat = storage.create_conversation(self.connection, 'owner-one')

    def test_persistence_order_isolation_and_additive_migration(self):
        request = str(uuid4())
        chat = self.chat['conversation_id']
        storage.begin_request(self.connection, chat, 'owner-one', request, 'Study tonight')
        storage.complete_request(self.connection, chat, request, {'message':'Suggested study, not saved.', 'actions':[]})
        self.connection.close()
        self.connection = sqlite3.connect(self.path)
        storage.migrate(self.connection)
        messages = storage.get_messages(self.connection, chat, 'owner-one')['messages']
        self.assertEqual([item['role'] for item in messages], ['user','assistant'])
        self.assertEqual([item['sequence_number'] for item in messages], [1,2])
        with self.assertRaises(ConversationNotFound):
            storage.get_messages(self.connection, chat, 'owner-two')
        other = storage.create_conversation(self.connection, 'owner-one')
        self.assertEqual(storage.completed_turns(self.connection, other['conversation_id'], 'owner-one'), [])

    def test_retry_and_concurrent_send_protection(self):
        chat, request = self.chat['conversation_id'], str(uuid4())
        storage.begin_request(self.connection, chat, 'owner-one', request, 'Question')
        self.assertFalse(storage.begin_request(self.connection, chat, 'owner-one', request, 'Question')[1])
        with self.assertRaises(ConversationConflict):
            storage.begin_request(self.connection, chat, 'owner-one', str(uuid4()), 'Another question')
        storage.fail_request(self.connection, chat, request)
        self.assertEqual(storage.completed_turns(self.connection, chat, 'owner-one'), [])
        storage.begin_request(self.connection, chat, 'owner-one', str(uuid4()), 'New question')

    def test_inspector_is_stored_separately_and_keys_are_redacted(self):
        chat, request = self.chat['conversation_id'], str(uuid4())
        storage.begin_request(self.connection, chat, 'owner-one', request, 'sk-placeholder-secret-123456789')
        storage.complete_request(self.connection, chat, request, {'message':'Hello','actions':[], 'agent_context':{'routing':{'stage':'stage_1'}}})
        turn = storage.completed_turns(self.connection, chat, 'owner-one')[0]
        self.assertNotIn('agent_context', turn['assistant'])
        self.assertIn('redacted', turn['user'])
        self.assertIn('agent_context', storage.get_messages(self.connection, chat, 'owner-one')['messages'][1])


if __name__ == '__main__':
    unittest.main()
