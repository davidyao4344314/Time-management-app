"""Offline restart, transaction and handoff failure checks."""
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.app import database
from backend.app.ai.actions import storage
from backend.app.ai.actions.contracts import ApprovalDecision
from backend.app.ai.actions.persistent_service import PersistentActionProposalService
from backend.app.ai.actions.service import ProposalConflict, ProposalNotFound
from backend.app.api.action_runtime import execution_resources
from backend.app.conversations import storage as chat_storage
from backend.app.dev.action_proposals import create_test_activity_proposal
from backend.app.planner import activity_service


class PersistentActionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'actions.db'
        with closing(sqlite3.connect(self.path)) as connection:
            database.create_tables(connection)
            chat_storage.migrate(connection)
            storage.migrate(connection)
        self.service = PersistentActionProposalService(self.open_store, execution_resources)
        self.proposal = create_test_activity_proposal()
        self.service.register('owner', self.proposal)

    @contextmanager
    def open_store(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            yield connection

    def count(self):
        with self.open_store() as connection:
            return connection.execute('SELECT count(*) FROM activities').fetchone()[0]

    def test_restart_keeps_pending_and_terminal_receipts_owner_scoped(self):
        restarted = PersistentActionProposalService(self.open_store, execution_resources)
        with self.assertRaises(ProposalNotFound):
            restarted.get_proposal('other', self.proposal.id)
        view = restarted.decide('owner', self.proposal.id, ApprovalDecision.APPROVE)
        self.assertEqual(view['status'], 'completed')
        self.assertEqual(self.service.get_proposal('owner', self.proposal.id), view)
        with self.assertRaises(ProposalConflict):
            self.service.decide('owner', self.proposal.id, ApprovalDecision.APPROVE)
        self.assertEqual(self.count(), 1)

    def test_concurrent_confirmations_change_state_once(self):
        def confirm(_):
            try:
                return self.service.decide('owner', self.proposal.id, ApprovalDecision.APPROVE)['status']
            except ProposalConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(list(executor.map(confirm, range(2))), ['completed', 'conflict'])
        self.assertEqual(self.count(), 1)

    def test_failure_after_insert_rolls_back_and_saves_failed_receipt(self):
        with patch.object(activity_service, 'get_activity_by_id', side_effect=RuntimeError('after write')):
            view = self.service.decide('owner', self.proposal.id, ApprovalDecision.APPROVE)
        self.assertEqual(view['status'], 'failed')
        self.assertIn('no activity changes', view['result']['message'])
        self.assertEqual(self.count(), 0)

    def test_receipt_write_failure_rolls_back_activity_and_keeps_pending(self):
        with patch.object(storage, 'finish', side_effect=sqlite3.OperationalError('receipt failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.service.decide('owner', self.proposal.id, ApprovalDecision.APPROVE)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.service.get_proposal('owner', self.proposal.id)['status'], 'pending_approval')

    def test_handoff_failure_rolls_back_assistant_and_authority(self):
        with self.open_store() as connection:
            chat = chat_storage.create_conversation(connection, 'owner')
            chat_storage.begin_request(connection, chat['conversation_id'], 'owner', 'request', 'Hello')
            def fail_after_insert():
                storage.insert_proposals(connection, 'owner', [create_test_activity_proposal()],
                    conversation_id=chat['conversation_id'], request_id='request')
                raise sqlite3.OperationalError('handoff failed')
            with self.assertRaises(sqlite3.OperationalError):
                chat_storage.complete_request(connection, chat['conversation_id'], 'request',
                    {'message': 'Review this proposal.', 'actions': []}, save_actions=fail_after_insert)
            self.assertEqual(len(chat_storage.request_messages(connection, chat['conversation_id'], 'request')), 1)
            self.assertEqual(len(self.service.list_proposals('owner')), 1)  # Only the setUp proposal.

