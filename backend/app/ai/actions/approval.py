"""Temporary trusted lifecycle state. No HTTP, persistence or automatic approval."""

from threading import RLock

from backend.app.ai.actions.contracts import (
    ActionLayerError, ActionProposal, ActionResult, ActionStatus, ApprovalDecision,
)


class ApprovalBoundary:
    """Snapshots are for display; only this backend-held state authorizes execution.

    A future HTTP adapter must authenticate the owner and pass only a proposal ID
    and explicit decision. It must never trust a browser's serialized status.
    """

    def __init__(self):
        self._proposals: dict[str, ActionProposal] = {}
        self._lock = RLock()

    def register(self, proposal: ActionProposal):
        # Revalidate even a model_copy snapshot, which can bypass Pydantic checks.
        proposal = ActionProposal.model_validate(proposal.model_dump())
        with self._lock:
            if proposal.status != ActionStatus.PENDING_APPROVAL:
                raise ActionLayerError("New proposals must be pending approval.")
            if proposal.id in self._proposals:
                raise ActionLayerError("The proposal is already registered.")
            self._proposals[proposal.id] = proposal.model_copy(deep=True)
            return self.get(proposal.id)

    def get(self, proposal_id: str) -> ActionProposal:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ActionLayerError("The proposal was not found.")
            return proposal.model_copy(deep=True)

    def decide(self, proposal_id: str, decision: ApprovalDecision):
        if not isinstance(decision, ApprovalDecision):
            raise ActionLayerError("An explicit approval or rejection decision is required.")
        with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status != ActionStatus.PENDING_APPROVAL:
                raise ActionLayerError("Only a pending proposal can receive a decision.")
            status = (ActionStatus.APPROVED if decision == ApprovalDecision.APPROVE
                      else ActionStatus.REJECTED)
            self._proposals[proposal_id] = proposal.model_copy(update={"status": status}, deep=True)
            return self.get(proposal_id)

    def begin_execution(self, proposal_id: str) -> ActionProposal:
        with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status != ActionStatus.APPROVED:
                raise ActionLayerError("The proposal is not approved for execution.")
            self._proposals[proposal_id] = proposal.model_copy(
                update={"status": ActionStatus.EXECUTING}, deep=True,
            )
            return self.get(proposal_id)

    def finish_execution(self, result: ActionResult):
        with self._lock:
            proposal = self.get(result.proposal_id)
            if proposal.status != ActionStatus.EXECUTING:
                raise ActionLayerError("Only an executing proposal can be completed.")
            status = ActionStatus.COMPLETED if result.success else ActionStatus.FAILED
            self._proposals[proposal.id] = proposal.model_copy(update={"status": status}, deep=True)
            return self.get(proposal.id)
