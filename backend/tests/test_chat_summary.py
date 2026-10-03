"""Local summary bounds, coverage and failure tests with mocked OpenAI."""
import sqlite3
import unittest
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.conversations import storage, summary, context
from backend.app.ai.agent.reasoning import build_agent_messages
from backend.app.conversations.contracts import ConversationConflict


class ChatSummaryTests(unittest.TestCase):
    def test_large_newest_turn_keeps_recent_context_without_changing_transcript(self):
        self.add_turns(2)
        self.connection.execute("UPDATE conversation_messages SET proposal_json=? WHERE role='assistant' AND sequence_number=4",
            ('{"message":"' + 'x' * 20000 + '","actions":[]}',))
        self.connection.commit()
        before = storage.completed_turns(self.connection, self.chat, 'owner')
        selected = context.build_chat_context(self.connection, self.chat, 'owner')['recent_turns']
        self.assertEqual(len(selected), 2)
        self.assertTrue(selected[-1]['context_truncated'])
        import json
        self.assertLessEqual(sum(len(json.dumps({'user':t['user'], 'assistant':t['assistant']},ensure_ascii=False))
                                 for t in selected), context.MAX_RECENT_CONTEXT_CHARS)
        self.assertEqual(storage.completed_turns(self.connection, self.chat, 'owner'), before)

    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        storage.migrate(self.connection)
        summary.migrate(self.connection)
        self.chat = storage.create_conversation(self.connection,'owner')['conversation_id']

    def add_turns(self,count):
        for number in range(count):
            request=str(uuid4())
            storage.begin_request(self.connection,self.chat,'owner',request,f'Question {number}')
            storage.complete_request(self.connection,self.chat,request,{'message':'Proposed a study session. Not saved.','actions':[]})

    def test_threshold_no_overlap_and_no_global_writes(self):
        with patch.object(summary,'get_max_recent_turns',return_value=5), patch.object(context,'get_max_recent_turns',return_value=5), \
                patch.object(summary,'is_openai_api_key_configured',return_value=True), \
                patch.object(summary,'get_agent_model_settings',return_value={'model':'existing-model','reasoning_effort':'none'}), \
                patch.dict(summary.os.environ,{'OPENAI_API_KEY':'offline-test-only'}), patch.object(summary,'OpenAI') as factory:
            self.add_turns(14)
            self.assertEqual(summary.update_summary(self.connection,self.chat,'owner')['status'],'not_needed')
            factory.assert_not_called()
            self.add_turns(1)
            factory.return_value.__enter__.return_value.responses.parse.return_value=SimpleNamespace(status='completed',output_parsed=summary.ChatSummary(text='Discussed study; actions remain proposals.'))
            result=summary.update_summary(self.connection,self.chat,'owner')
            self.assertEqual(result['summary']['through_sequence_number'],20)
            selected=context.build_chat_context(self.connection,self.chat,'owner')
            self.assertGreater(selected['recent_turns'][0]['sequence_number'],20)
            inputs=build_agent_messages('Follow up',{},selected['recent_turns'],chat_summary=selected['summary'])
            self.assertIn('current_chat_summary',inputs[0]['content'])
            self.assertEqual(len(storage.get_messages(self.connection,self.chat,'owner')['messages']),30)
            # Raising the recent limit makes overlapping summary ineligible.
            with patch.object(context,'get_max_recent_turns',return_value=20):
                self.assertIsNone(context.build_chat_context(self.connection,self.chat,'owner')['summary'])

    def test_failed_summary_preserves_transcript_and_releases_reservation(self):
        self.add_turns(15)
        with patch.object(summary,'get_max_recent_turns',return_value=5), \
                patch.object(summary,'is_openai_api_key_configured',return_value=True), \
                patch.object(summary,'get_agent_model_settings',return_value={'model':'existing-model','reasoning_effort':'none'}), \
                patch.dict(summary.os.environ,{'OPENAI_API_KEY':'offline-test-only'}), patch.object(summary,'OpenAI') as factory:
            factory.return_value.__enter__.return_value.responses.parse.return_value=SimpleNamespace(status='incomplete',output_parsed=None)
            with self.assertRaises(ConversationConflict):
                summary.update_summary(self.connection,self.chat,'owner')
        self.assertIsNone(summary.read_summary(self.connection,self.chat))
        self.assertEqual(self.connection.execute('SELECT updating FROM conversation_summaries').fetchone()[0],0)
        self.assertEqual(len(storage.completed_turns(self.connection,self.chat,'owner')),15)
