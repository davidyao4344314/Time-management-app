"""Pure selection schemas shared by the existing routing stages."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator
from backend.app.ai.memory.contracts import MemorySelection


class AgentRoutingDecision(BaseModel):
    """Scheduling and optional memory selection shared by Stage 2 and Stage 3."""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal[
        "study_planning", "schedule_query", "exam_query",
        "activity_query", "general_question",
    ]
    time_scope: Literal["today", "tomorrow", "week", "this_week", "next_week", "month", "all", "unspecified"]
    include_activities: bool
    include_exams: bool
    memory: MemorySelection | None = None


class AgentIntentClassification(AgentRoutingDecision):
    """Stage 2 adds only a confidence signal to the shared routing decision."""

    confidence: Literal["high", "low"]


def validate_intent_classification(value):
    """Reject unknown labels, non-booleans, and extra response fields."""
    return AgentIntentClassification.model_validate(value)


def validate_routing_decision(value):
    """Validate shared routing fields, including Stage 3 output."""
    return AgentRoutingDecision.model_validate(value)


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    activities_scope: Literal["today", "tomorrow", "week", "this_week", "next_week", "month", "all"] | None
    include_exams: bool
    exam_scope: Literal["today", "tomorrow", "week", "this_week", "next_week", "month", "upcoming"] | None
    memory: MemorySelection | None = None

    @model_validator(mode="after")
    def consistent_exam_scope(self):
        if self.include_exams != (self.exam_scope is not None):
            raise ValueError("Exam scope and inclusion must agree.")
        return self
