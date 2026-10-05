"""Bounded routing evidence and reviewed labels, never schedule facts or actions."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.ai.context.contracts import ContextSelection, AgentRoutingDecision
from backend.app.ai.context.adaptive.settings import SCHEMA_VERSION, ROUTER_VERSION


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RoutingCandidate(StrictRecord):
    stage: Literal["stage_1", "stage_2", "stage_3", "safe_fallback"]
    selection: ContextSelection | None = None
    classification: AgentRoutingDecision | None = None
    confidence: Literal["high", "low"] | None = None
    status: Literal["matched", "unresolved", "unavailable", "fallback"]


class RoutingEvent(StrictRecord):
    event_id: str = Field(min_length=1, max_length=128)
    owner_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    timestamp: str
    schema_version: int = SCHEMA_VERSION
    router_version: str = ROUTER_VERSION
    classifier_model: str = Field(max_length=80)
    classifier_version: str = Field(max_length=80)
    pattern: str = Field(max_length=600)
    request_excerpt: str | None = Field(default=None, max_length=600)
    context_dependent: bool = False
    candidates: list[RoutingCandidate] = Field(max_length=4)
    initial_selection: ContextSelection
    final_selection: ContextSelection
    initial_status: dict[Literal["activities", "exams", "current_chat", "global_memory", "files"],
                         Literal["provided", "empty", "not_selected", "unavailable"]]
    final_status: dict[Literal["activities", "exams", "current_chat", "global_memory", "files"],
                       Literal["provided", "empty", "not_selected", "unavailable"]]
    excluded_sources: list[Literal["activities", "exams", "files"]] = Field(default_factory=list, max_length=3)
    recovery_requested: bool = False
    recovery_completed: bool = False
    audit_selected: bool = False

    @model_validator(mode="after")
    def valid_timestamp(self):
        stamp = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Routing evidence requires a timestamp with timezone.")
        return self


SelectionField = Literal["activities_scope", "include_exams", "exam_scope", "memory"]
SELECTION_FIELDS = frozenset({"activities_scope", "include_exams", "exam_scope", "memory"})


class RoutingLabel(StrictRecord):
    signal: Literal["developer", "user_structured", "stage3_disagreement", "context_recovery"]
    status: Literal["pending", "confirmed", "rejected"]
    selection: ContextSelection
    confirmed_fields: list[SelectionField] = Field(default_factory=list, max_length=4)
    classification: AgentRoutingDecision | None = None
    example_approved: bool = False

    @model_validator(mode="after")
    def trusted_confirmation(self):
        if len(set(self.confirmed_fields)) != len(self.confirmed_fields):
            raise ValueError("Confirmed fields must be unique.")
        if self.status == "confirmed":
            if self.signal not in {"developer", "user_structured"} or not self.confirmed_fields:
                raise ValueError("Only an explicit review/correction can confirm routing.")
        elif self.confirmed_fields or self.example_approved:
            raise ValueError("Unconfirmed labels cannot provide trusted fields/examples.")
        if self.example_approved and (not self.complete or self.classification is None):
            raise ValueError("Examples need a complete reviewed classification.")
        return self

    @property
    def complete(self):
        return self.status == "confirmed" and set(self.confirmed_fields) == SELECTION_FIELDS


class PatternApproval(StrictRecord):
    schema_version: int = SCHEMA_VERSION
    router_version: str = ROUTER_VERSION
    selection: ContextSelection
    approved_label_ids: list[str] = Field(max_length=100)
    shadow_reviewed: Literal[True]
    suspended: bool = False
