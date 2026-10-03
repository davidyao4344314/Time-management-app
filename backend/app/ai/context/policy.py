"""Small read-only guards for explicitly excluded observation sources."""

import re


_EXCLUSION = re.compile(
    r"\b(?:(?:don't|dont|do not|never)\s+"
    r"(?:use|show|include|load|fetch|read|consult|access|consider|look at)|"
    r"exclude|skip|ignore|avoid|without)\b"
)
_CLAUSE_BOUNDARY = re.compile(
    r"[.!?;,\n]|\b(?:but|just|instead|then)\b|"
    r"\b(?:and|or)\s+(?=(?:use|show|include|tell|give|check|fetch|read)\b)"
)


def excluded_context_sources(user_message):
    """Recognize explicit source exclusions, not arbitrary negative statements.

    Calendar/schedule access includes both activities and dated exams. Excluding
    exams alone still permits activities. This is a conservative phrase guard,
    not a replacement for the semantic classifier.
    """
    message = user_message.casefold().replace("’", "'")
    excluded = set()
    for clause in _CLAUSE_BOUNDARY.split(message):
        match = _EXCLUSION.search(clause)
        if match is None:
            continue
        targets = clause[match.end():]
        if re.search(r"\b(?:calendar|schedule|timetable)\b", targets):
            excluded.update(("activities", "exams"))
        if re.search(r"\b(?:activity|activities)\b", targets):
            excluded.add("activities")
        if re.search(r"\b(?:exam|exams|test|tests|assessment|assessments|deadline|deadlines|quiz|quizzes)\b", targets):
            excluded.add("exams")
    return frozenset(excluded)


def apply_context_exclusions(selection, excluded_sources):
    """Return a new selection; exclusions cannot be overridden by a model."""
    selected = dict(selection)
    if "activities" in excluded_sources:
        selected["activities_scope"] = None
    if "exams" in excluded_sources:
        selected.update(include_exams=False, exam_scope=None)
    return selected
