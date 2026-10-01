"""Validate agent messages, proposed actions, and optional memory requests."""

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from backend.app.actions.contracts import AddActivityAction
from backend.app.memory.contracts import MemoryRequest


class AgentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str
    actions: list[AddActivityAction]
    memory_request: MemoryRequest | None = None

    @model_validator(mode="after")
    def validate_message(self):
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("A user-facing message is required.")
        return self


class InvalidProposalError(ValueError):
    """The model did not return an allowed, complete proposal."""


def validate_agent_proposal(value):
    """Reject unknown tools, malformed activities, and invalid memory requests."""
    try:
        if isinstance(value, AgentProposal):
            value = value.model_dump()
        return AgentProposal.model_validate(value)
    except ValidationError:
        raise InvalidProposalError("The model returned an invalid proposal.") from None
