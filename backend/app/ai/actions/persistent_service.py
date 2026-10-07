"""Persistent approval lifecycle; the tool change and receipt commit together."""
from backend.app.ai.actions import storage
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ActionLayerError, ActionProposal, ActionResult, ApprovalDecision
from backend.app.ai.actions.service import ProposalConflict, ProposalNotFound


class PersistentActionProposalService:
    def __init__(self, store_factory, executor_factory):
        self._store_factory = store_factory
        self._executor_factory = executor_factory

    def register(self, owner, proposal):
        with self._store_factory() as connection, connection:
            storage.insert_proposals(connection, owner, [proposal])
            return self._get(connection, owner, proposal.id)

    @staticmethod
    def _row(connection, owner, identifier):
        row = storage.read_proposal(connection, owner, identifier)
        if row is None:
            raise ProposalNotFound('Action proposal not found.')
        return row

    def _get(self, connection, owner, identifier):
        return storage.public_view(identifier, self._row(connection, owner, identifier))

    def get_proposal(self, owner, identifier):
        with self._store_factory() as connection:
            return self._get(connection, owner, identifier)

    def list_proposals(self, owner):
        with self._store_factory() as connection:
            return [storage.public_view(row[0], row[1:]) for row in connection.execute(
                'SELECT proposal_id,proposal_json,status,result_json FROM action_proposals WHERE owner_id=? ORDER BY created_at,proposal_id', (owner,))]

    def decide(self, owner, identifier, decision):
        if not isinstance(decision, ApprovalDecision):
            raise ActionLayerError('Choose an explicit approval or rejection decision.')
        with self._store_factory() as connection, connection:
            # One cross-process write lock: restart/network retries cannot replay a mutation.
            connection.execute('BEGIN IMMEDIATE')
            row = self._row(connection, owner, identifier)
            if row[1] != 'pending_approval':
                raise ProposalConflict('This proposal is no longer pending. Refresh its status.')
            if decision == ApprovalDecision.REJECT:
                storage.finish(connection, owner, identifier, 'rejected')
            else:
                approval = ApprovalBoundary()
                proposal = ActionProposal.model_validate_json(row[0])
                approval.register(proposal)
                approval.decide(identifier, decision)
                # A failed handler may already have issued writes: roll them ALL back.
                connection.execute('SAVEPOINT action_execution')
                with self._executor_factory(approval, connection=connection) as executor:
                    result = executor.execute(identifier)
                if not result.success:
                    connection.execute('ROLLBACK TO action_execution')
                    result = ActionResult(proposal_id=identifier, success=False, error=result.error,
                        message='Action failed; no activity changes were saved.')
                connection.execute('RELEASE action_execution')
                storage.finish(connection, owner, identifier, 'completed' if result.success else 'failed', result)
            return self._get(connection, owner, identifier)
