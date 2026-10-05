"""Validate agent messages, proposed actions, and read-only context requests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.app.ai.actions.contracts import AddActivityAction
from backend.app.ai.memory.contracts import MemoryRequest
from backend.app.files.contracts import MAX_QUERY_CHARS, validate_query


class MissingContextRequest(BaseModel):
    """A supported observation and symbolic scope, never a mutation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["activities", "exams"]
    time_scope: Literal[
        "today", "tomorrow", "week", "this_week", "next_week", "month", "all", "upcoming",
    ]

    @model_validator(mode="after")
    def validate_scope(self):
        if ((self.source == "activities" and self.time_scope == "upcoming")
                or (self.source == "exams" and self.time_scope == "all")):
            raise ValueError("The time scope is not supported by this source.")
        return self


class MissingFileContextRequest(BaseModel):
    """A bounded topic/name query against managed files, not a file-open tool."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["files"]
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)

    @model_validator(mode="after")
    def safe_query(self):
        self.query = validate_query(self.query)
        return self


class AgentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str | None
    actions: list[AddActivityAction]
    memory_request: MemoryRequest | None = None
    missing_context: list[MissingContextRequest | MissingFileContextRequest] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_message(self):
        if self.message is not None:
            self.message = self.message.strip()
        if self.missing_context:
            sources = [request.source for request in self.missing_context]
            if len(sources) != len(set(sources)):
                raise ValueError("Request each missing observation at most once.")
            if self.actions:
                raise ValueError("Context requests cannot also propose mutations.")
        elif not self.message:
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
