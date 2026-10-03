"""Persistent conversation behavior in disposable databases; no model calls."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


class ConversationAPITests(unittest.TestCase):
    def test_verified_owner_isolation_and_restart(self):
        from backend.app import database
        from backend.app.infrastructure import identity
        from backend.app.api.conversations import router
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(database, 'db_file', Path(directory)/'db.sqlite'), \
                patch.object(identity, 'IDENTITY_KEY_FILE', Path(directory)/'key'):
            app = FastAPI()
            app.include_router(router)
            first, second = TestClient(app), TestClient(app)
            created = first.post('/conversations', json={})
            self.assertEqual(created.status_code, 200)
            chat = created.json()['conversation_id']
            self.assertFalse(created.json()['memory_sharing_enabled'])
            self.assertEqual(second.get(f'/conversations/{chat}/messages').status_code, 404)
            self.assertEqual(first.get(f'/conversations/{chat}/messages').status_code, 200)
            self.assertEqual(len(first.get('/conversations').json()['conversations']), 1)
            second.cookies.set('ai_owner', first.cookies.get('ai_owner'))
            self.assertEqual(second.get(f'/conversations/{chat}/messages').status_code, 404)

    def test_send_loads_local_history_and_retries_without_another_model_call(self):
        from backend.app import database
        from backend.app.conversations import service
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(database, 'db_file', Path(directory)/'db.sqlite'), \
                patch.object(service, 'is_openai_api_key_configured', return_value=True), \
                patch.object(service, 'get_agent_proposal', return_value={'message':'Try COMPSCI.','actions':[]}) as model:
            chat = service.create_chat('owner')['conversation_id']
            request = str(uuid4())
            first = service.send_message('owner',chat,request,'Study tonight')
            second = service.send_message('owner',chat,request,'Study tonight')
            self.assertEqual(first, second)
            self.assertEqual(model.call_count, 1)
            service.send_message('owner',chat,str(uuid4()),'Make it later')
            self.assertEqual(model.call_args.args[2][0]['user'], 'Study tonight')
            other = service.create_chat('owner')['conversation_id']
            service.send_message('owner',other,str(uuid4()),'New topic')
            self.assertEqual(model.call_args.args[2], [])
            self.assertEqual(model.call_args.kwargs['session_id'], other)

    def test_failure_retains_user_and_excludes_failed_turn(self):
        from backend.app import database
        from backend.app.conversations import service
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(database, 'db_file', Path(directory)/'db.sqlite'), \
                patch.object(service, 'is_openai_api_key_configured', return_value=True), \
                patch.object(service, 'get_agent_proposal', side_effect=RuntimeError('offline failure')) as model:
            chat = service.create_chat('owner')['conversation_id']
            request = str(uuid4())
            with self.assertRaises(RuntimeError):
                service.send_message('owner',chat,request,'Question')
            retry = service.send_message('owner',chat,request,'Question')
            self.assertEqual(retry['status'], 'failed')
            self.assertEqual(model.call_count,1)
            self.assertEqual(service.read_chat('owner',chat)['messages'][0]['status'],'failed')


class ConversationMemoryTests(unittest.TestCase):
    def test_local_lookup_and_opt_in_global_isolation(self):
        import json
        from backend.app.ai.memory import archive_store
        from backend.app.conversations.memory_context import retrieve_for_chat
        with tempfile.TemporaryDirectory() as directory, patch.object(archive_store,'ARCHIVE_FILE',Path(directory)/'archive.jsonl'):
            connection = sqlite3.connect(':memory:')
            self.addCleanup(connection.close)
            storage.migrate(connection)
            a = storage.create_conversation(connection,'owner')['conversation_id']
            b = storage.create_conversation(connection,'owner')['conversation_id']
            foreign = storage.create_conversation(connection,'other')['conversation_id']
            request = str(uuid4())
            storage.begin_request(connection,a,'owner',request,'COMPSCI local history')
            storage.complete_request(connection,a,request,{'message':'Only this chat','actions':[]})
            selection = {'sources':['raw_archive'],'query':{'time_reference':None,'search_terms':['COMPSCI']},'scope':'current_chat'}
            self.assertEqual(len(retrieve_for_chat(connection,'owner',a,selection)['items']),1)
            self.assertEqual(retrieve_for_chat(connection,'owner',b,selection)['items'],[])
            rows = [{'turn_id':str(uuid4()),'session_id':identifier,'timestamp':'2026-10-03T12:00:00+13:00',
                     'turn':{'user':'COMPSCI','assistant':{'message':text,'actions':[]}}}
                    for identifier,text in ((a,'Authorized'),(foreign,'PRIVATE OTHER OWNER'))]
            archive_store.ARCHIVE_FILE.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            selection['scope']='global'
            self.assertEqual(retrieve_for_chat(connection,'owner',b,selection)['items'],[])
            storage.set_memory_sharing(connection,a,'owner',True)
            storage.set_memory_sharing(connection,foreign,'other',True)
            result = retrieve_for_chat(connection,'owner',b,selection)
            self.assertEqual(len(result['items']),1)
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertEqual(result['items'][0]['conversation_id'],a)
