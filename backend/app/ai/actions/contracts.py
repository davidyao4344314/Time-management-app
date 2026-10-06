"""Action/proposal contracts; no execution, storage or provider dependencies."""

import re
from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


class AddActivityArguments(BaseModel):
    """The same eight fields accepted by the existing Add Activity API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    category: str
    subject: str | None
    activity_type: Literal["one_time", "daily", "weekly"]
    date: str | None
    weekday: str | None
    start_time: str | None
    end_time: str | None

    @model_validator(mode="after")
    def validate_activity_fields(self):
        self.name = self.name.strip()
        self.category = self.category.strip()
        if self.subject is not None:
            self.subject = self.subject.strip() or None
        if not self.name or not self.category:
            raise ValueError("Activity name and category are required.")

        if self.activity_type == "one_time":
            if self.date is None or self.weekday is not None:
                raise ValueError("One-time activities need a date and no weekday.")
            try:
                if date.fromisoformat(self.date).isoformat() != self.date:
                    raise ValueError
            except ValueError:
                raise ValueError("Activity date must be YYYY-MM-DD.") from None
        elif self.activity_type == "weekly":
            if self.date is not None or self.weekday not in WEEKDAYS:
                raise ValueError("Weekly activities need a valid weekday and no date.")
        elif self.date is not None or self.weekday is not None:
            raise ValueError("Daily activities cannot have a date or weekday.")

        for value in (self.start_time, self.end_time):
            if value is not None:
                if not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise ValueError("Activity times must use HH:MM.")
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError:
                    raise ValueError("Activity times must be valid clock times.") from None
        if self.start_time is not None and self.end_time is not None:
            if self.start_time >= self.end_time:
                raise ValueError("End time must be later than start time.")
        return self


class AddActivityAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool: Literal["add_activity"]
    arguments: AddActivityArguments


class DeleteActivityArguments(BaseModel):
    """One exact database record, never a name search or bulk deletion."""

    model_config = ConfigDict(extra="forbid", strict=True)
    activity_id: int = Field(gt=0, description="Existing activity ID from current app observations.")
    expected_name: str = Field(min_length=1, description="Exact current name of that activity, not a guessed name.")

    @model_validator(mode="after")
    def meaningful_name(self):
        if not self.expected_name.strip():
            raise ValueError("The current activity name is required.")
        return self


class DeleteActivityAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: Literal["delete_activity"]
    arguments: DeleteActivityArguments


class ActionRoute(str, Enum):
    NONE = "none"
    TOOL_ACTION = "tool_action"
    RESPONSE_PLAN = "response_plan"


class ActionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ToolActionRequest(BaseModel):
    """Public tool request only: the model cannot supply approval or identity."""

    model_config = ConfigDict(extra="forbid", strict=True)
    tool: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


class ActionProposal(BaseModel):
    """Backend-created display snapshot, not proof of a user's approval."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    action_type: Literal["tool_action"] = "tool_action"
    tool_name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]
    display_title: str = Field(min_length=1)
    display_description: str
    status: ActionStatus = ActionStatus.PENDING_APPROVAL
    requires_approval: Literal[True] = True


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    proposal_id: str = Field(min_length=1)
    success: bool
    result: dict[str, JsonValue] | None = None
    error: str | None = None
    message: str

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.success and self.error is not None:
            raise ValueError("Successful actions cannot also have an error.")
        if not self.success and (not self.error or self.result is not None):
            raise ValueError("Failed actions need an error and no success result.")
        return self


class ActionRoutingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    route: ActionRoute
    proposals: list[ActionProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_route(self):
        if (self.route == ActionRoute.TOOL_ACTION) != bool(self.proposals):
            raise ValueError("Only the tool-action route contains proposals.")
        return self


class ActionLayerError(ValueError):
    """Controlled boundary error; never contains raw model/provider exceptions."""
