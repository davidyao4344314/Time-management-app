"""Memory request and archive-output formats, independent of agent/storage code."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


PROTECTED_CATEGORIES = frozenset({
    "explicit_memory", "goal", "preference", "decision", "requirement",
    "constraint", "long_term_plan", "unfinished_task", "project_architecture",
    "other_long_term",
})
COMPACTABLE_CATEGORIES = frozenset({
    "temporary_debugging", "one_off_question", "repeated_explanation",
    "casual_conversation", "resolved_issue", "transient_information",
    "duplicate_information", "other_short_term",
})
BASE_ARCHIVE_CATEGORIES = (
    "activities", "exams_tests", "study_topics", "technical_issues", "general",
)


class MemoryRequest(BaseModel):
    """A request to retrieve older conversation later, not retrieved content."""

    model_config = ConfigDict(extra="forbid", strict=True)

    time_reference: Literal[
        "today", "yesterday", "last_week", "this_week",
        "last_month", "this_month", "unspecified",
    ] | None
    search_terms: list[str]

    @model_validator(mode="after")
    def validate_search(self):
        if len(self.search_terms) > 5:
            raise ValueError("Memory requests can contain at most five search terms.")
        generic_words = {"the", "what", "did", "we", "about", "was", "that", "before"}
        cleaned_terms = []
        for term in self.search_terms:
            cleaned = term.strip()
            words = re.findall(r"[\w]+", cleaned.casefold())
            if not cleaned or not words or all(word in generic_words for word in words):
                raise ValueError("Memory search terms must name a meaningful topic.")
            cleaned_terms.append(cleaned)
        self.search_terms = cleaned_terms
        return self


class ArchiveCandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_index: int
    status: Literal["protected", "compactable"]
    category: Literal[
        "explicit_memory", "goal", "preference", "decision", "requirement",
        "constraint", "long_term_plan", "unfinished_task", "project_architecture",
        "other_long_term", "temporary_debugging", "one_off_question",
        "repeated_explanation", "casual_conversation", "resolved_issue",
        "transient_information", "duplicate_information", "other_short_term",
    ]
    reason: str

    @model_validator(mode="after")
    def validate_category(self):
        allowed = PROTECTED_CATEGORIES if self.status == "protected" else COMPACTABLE_CATEGORIES
        if self.category not in allowed:
            raise ValueError("The category does not match the classification status.")
        if not self.reason.strip():
            raise ValueError("A short classification reason is required.")
        self.reason = self.reason.strip()
        return self


class ArchiveClassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    classifications: list[ArchiveCandidateDecision]


class ArchiveCategorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: list[str]
    keywords: list[str]

    @model_validator(mode="after")
    def validate_compact_content(self):
        if len(self.summary) > 5 or len(self.keywords) > 8:
            raise ValueError("Archive category output must remain compact.")
        cleaned_summary = []
        for item in self.summary:
            item = item.strip()
            if not item or len(item) > 240 or "```" in item:
                raise ValueError("Archive summary items must be short plain text.")
            cleaned_summary.append(item)
        cleaned_keywords = []
        for keyword in self.keywords:
            keyword = keyword.strip()
            if not keyword or len(keyword) > 60:
                raise ValueError("Archive keywords must be short and meaningful.")
            cleaned_keywords.append(keyword)
        self.summary = cleaned_summary
        self.keywords = cleaned_keywords
        return self


class ArchiveCategorizedSummary(BaseModel):
    """Five fixed categories plus a minimal signal for optional Stage 4.5 review."""

    model_config = ConfigDict(extra="forbid", strict=True)

    activities: ArchiveCategorySummary
    exams_tests: ArchiveCategorySummary
    study_topics: ArchiveCategorySummary
    technical_issues: ArchiveCategorySummary
    general: ArchiveCategorySummary
    needs_category_review: bool
    uncategorized_item_refs: list[int]

    @model_validator(mode="after")
    def validate_review_signal(self):
        refs = self.uncategorized_item_refs
        if len(refs) > len(self.general.summary) or len(set(refs)) != len(refs):
            raise ValueError("Review refs must be unique general-summary positions.")
        if any(index < 0 or index >= len(self.general.summary) for index in refs):
            raise ValueError("Review refs must point to general-summary items.")
        if self.needs_category_review != bool(refs):
            raise ValueError("Review signal and refs must agree.")
        return self


class ArchiveCategoryProposal(BaseModel):
    """Strict model proposal; Python still decides whether to accept it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    needs_new_category: bool
    proposed_category: str | None
    reason: str
    example_topics: list[str]
    item_refs: list[int]

    @model_validator(mode="after")
    def validate_shape(self):
        self.reason = self.reason.strip()
        if not self.reason or len(self.reason) > 300:
            raise ValueError("A short reason is required.")
        if len(self.example_topics) > 5 or any(
            not topic.strip() or len(topic) > 60 for topic in self.example_topics
        ):
            raise ValueError("Example topics must be short.")
        self.example_topics = [topic.strip() for topic in self.example_topics]
        if len(self.item_refs) > 5 or len(set(self.item_refs)) != len(self.item_refs):
            raise ValueError("Item refs must be unique and limited.")
        if self.needs_new_category:
            if not self.proposed_category or not self.example_topics or not self.item_refs:
                raise ValueError("A category proposal needs a name, topics and refs.")
        elif self.proposed_category is not None or self.example_topics or self.item_refs:
            raise ValueError("No-category proposals must leave all proposal fields empty.")
        return self
