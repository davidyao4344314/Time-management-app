"""Pure category safeguards; no model requests or file operations."""

import re

from backend.app.memory.protection import STRONG_PROTECTION_RULES

MAX_CATEGORY_NAME_LENGTH = 28

# Deterministic safeguards; the model cannot expand the accepted taxonomy itself.
_CATEGORY_ALIASES = {
    "activities": {
        "activity", "activities", "calendar", "calendar_planning", "class",
        "classes", "schedule", "scheduling", "timetable", "study_sessions",
    },
    "exams_tests": {
        "exam", "exams", "test", "tests", "quiz", "quizzes", "assessment",
        "assessments", "deadline", "deadlines", "exam_prep", "exam_revision",
    },
    "study_topics": {
        "study", "studying", "study_topic", "learning", "revision",
        "subject", "subjects", "coursework",
    },
    "technical_issues": {
        "coding", "code", "programming", "bug", "bugs", "debugging",
        "technical", "technical_issue", "canvas_errors", "canvas_import_bug",
        "fastapi_errors",
    },
    "general": {"misc", "miscellaneous", "other", "uncategorized", "random"},
}
_EXISTING_THEME_WORDS = frozenset({
    "activity", "activities", "calendar", "schedule", "scheduling",
    "timetable", "class", "classes", "exam", "exams", "test", "tests",
    "quiz", "quizzes", "assessment", "assessments", "revision", "study",
    "studying", "technical", "coding", "programming", "bug", "bugs",
    "debugging", "canvas", "fastapi", "coursework", "deadline", "deadlines",
})
_PROTECTED_CATEGORY_WORDS = frozenset({
    "goal", "goals", "preference", "preferences", "decision", "decisions",
    "requirement", "requirements", "constraint", "constraints", "plan",
    "plans", "memory", "architecture", "unfinished", "explicit",
})
_VAGUE_CATEGORY_WORDS = frozenset({
    "my", "random", "things", "stuff", "notes", "other", "misc", "for",
})
_PROTECTED_TEXT_PHRASES = tuple(phrase for phrase, _ in STRONG_PROTECTION_RULES) + (
    "long-term goal", "long term goal", "user's goal", "user’s goal",
    "user prefers", "user decided", "we decided", "project architecture",
    "project requirement", "explicit memory", "remember this",
)


def _contains_protected_content(text):
    normalized = text.casefold().replace("’", "'")
    return any(phrase.replace("’", "'") in normalized for phrase in _PROTECTED_TEXT_PHRASES)


def _category_rejection(name, existing_names):
    if len(name) > MAX_CATEGORY_NAME_LENGTH or not re.fullmatch(
        r"[a-z]+(?:_[a-z]+){0,2}", name
    ):
        return "Invalid category name; use a short lowercase snake_case label."
    if name in existing_names:
        return "The category already exists."
    words = set(name.split("_"))
    if words & _PROTECTED_CATEGORY_WORDS:
        return "Protected memory needs its separate durable-memory path."
    if words & _VAGUE_CATEGORY_WORDS:
        return "The category is too vague or too specific."
    if name in set().union(*_CATEGORY_ALIASES.values()) or words & _EXISTING_THEME_WORDS:
        return "The proposed category fits an existing category."
    return None


def _topic_words(text):
    """Use a small lexical check that does not require another model call."""
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return {word[:-1] if len(word) > 3 and word.endswith("s") else word
            for word in words if len(word) >= 2}
