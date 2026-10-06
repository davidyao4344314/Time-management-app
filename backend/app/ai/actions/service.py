"""Temporary owner-scoped proposal orchestration; no HTTP, SQL or model calls."""

from threading import RLock

from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ActionLayerError, ActionStatus, ApprovalDecision


class ProposalNotFound(ActionLayerError):
    pass


class ProposalConflict(ActionLayerError):
    pass


class ActionProposalService:
    """Reuse the approval lifecycle; executor_factory owns execution resources.

    State is process-local. A restart invalidates pending proposals. Owners must
    come from the HTTP adapter's verified identity, never a browser-supplied body.
    """

    def __init__(self, executor_factory):
        self._approval = ApprovalBoundary()
        self._executor_factory = executor_factory
        self._owners = {}
        self._results = {}
        self._lock = RLock()

    def register(self, owner, proposal):
        with self._lock:
            stored = self._approval.register(proposal)
            self._owners[stored.id] = owner
            return self._view(stored.id)

    def _require_owner(self, owner, proposal_id):
        if self._owners.get(proposal_id) != owner:
            raise ProposalNotFound("Action proposal not found.")

    def _view(self, proposal_id):
        proposal = self._approval.get(proposal_id)
        result = self._results.get(proposal_id)
        # Only presentation fields, not tool arguments or implementation metadata.
        return {
            "id": proposal.id,
            "display_title": proposal.display_title,
            "display_description": proposal.display_description,
            "status": proposal.status.value,
            "requires_approval": proposal.requires_approval,
            "result": result.model_dump(mode="json") if result is not None else None,
        }

    def list_proposals(self, owner):
        with self._lock:
            return [self._view(proposal_id) for proposal_id, stored_owner in self._owners.items()
                    if stored_owner == owner]

    def get_proposal(self, owner, proposal_id):
        with self._lock:
            self._require_owner(owner, proposal_id)
            return self._view(proposal_id)

    def decide(self, owner, proposal_id, decision):
        if not isinstance(decision, ApprovalDecision):
            raise ActionLayerError("Choose an explicit approval or rejection decision.")
        # Serialize the short local decision/execution path, including duplicate
        # confirmations. ApprovalBoundary remains authoritative for execution.
        with self._lock:
            self._require_owner(owner, proposal_id)
            if self._approval.get(proposal_id).status != ActionStatus.PENDING_APPROVAL:
                raise ProposalConflict("This proposal is no longer pending. Refresh its status.")
            if decision == ApprovalDecision.REJECT:
                self._approval.decide(proposal_id, decision)
            else:
                # Open resources before approval: failure to open leaves it pending.
                with self._executor_factory(self._approval) as executor:
                    self._approval.decide(proposal_id, decision)
                    self._results[proposal_id] = executor.execute(proposal_id)
            return self._view(proposal_id)
