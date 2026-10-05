"""Small read-only guards for explicitly excluded observation sources."""

import re
from backend.app.ai.context.exam_policy import explicit_exam_filter


_EXCLUSION = re.compile(
    r"\b(?:(?:don't|dont|do not|never)\s+"
    r"(?:use|show|include|load|fetch|read|consult|access|consider|look at)|"
    r"exclude|skip|ignore|avoid|without)\b"
)
_CLAUSE_BOUNDARY = re.compile(
    r"[.!?;,\n]|\b(?:but|just|instead|then)\b|"
    r"\b(?:and|or)\s+(?=(?:use|show|include|tell|give|check|fetch|read)\b)"
)
_NEGATED_EXCLUSION = re.compile(r"\b(?:don't|dont|do not|never)\s+$")
_SOURCE_OBJECT = re.compile(
    r"\s+(?:(?:me|my|the|any|all|our|your|personal|scheduled|upcoming|"
    r"current|existing|stored|uploaded|imported|daily|weekly|formal|final|of)\s+)*"
    r"(?P<source>calendar|schedule|timetable|activity|activities|exam|exams|"
    r"test|tests|assessment|assessments|deadline|deadlines|quiz|quizzes|file|files|document|documents)\b"
)
_WITHOUT_ACCESS = re.compile(
    r"^\s+(?:using|showing|including|loading|fetching|reading|consulting|"
    r"accessing|considering|looking at)\b"
)
_NEXT_SOURCE = re.compile(r"^\s+(?:and|or)\b")


def excluded_context_sources(user_message):
    """Recognize explicit source exclusions, not arbitrary negative statements.

    Calendar/schedule access includes both activities and dated exams. Excluding
    exams alone still permits activities. This is a conservative phrase guard,
    not a replacement for the semantic classifier.
    """
    message = user_message.casefold().replace("’", "'")
    excluded = set()
    for clause in _CLAUSE_BOUNDARY.split(message):
        for match in _EXCLUSION.finditer(clause):
            # "Don't ignore exams" negates exclusion, rather than requesting it.
            if _NEGATED_EXCLUSION.search(clause[:match.start()]):
                continue
            targets = clause[match.end():]
            if match.group() == "without":
                access = _WITHOUT_ACCESS.match(targets)
                if access:
                    targets = targets[access.end():]
            # Require a direct source object: "without forgetting my exams" is
            # not an exclusion. Stop before unrelated text or a positive request.
            while source_match := _SOURCE_OBJECT.match(targets):
                source = source_match.group("source")
                if source in {"calendar", "schedule", "timetable"}:
                    excluded.update(("activities", "exams"))
                elif source in {"activity", "activities"}:
                    excluded.add("activities")
                elif source in {"file", "files", "document", "documents"}:
                    excluded.add("files")
                elif source in {"quiz", "quizzes", "test", "tests", "assessment", "assessments"} and explicit_exam_filter(message) == "formal_exams":
                    # Excluding quizzes while requesting formal exams narrows
                    # the subset; it must not block the entire exams source.
                    pass
                else:
                    excluded.add("exams")
                targets = targets[source_match.end():]
                conjunction = _NEXT_SOURCE.match(targets)
                if conjunction is None:
                    break
                targets = targets[conjunction.end():]
    return frozenset(excluded)


def apply_context_exclusions(selection, excluded_sources):
    """Return a new selection; exclusions cannot be overridden by a model."""
    selected = dict(selection)
    if "activities" in excluded_sources:
        selected["activities_scope"] = None
    if "exams" in excluded_sources:
        selected.update(include_exams=False, exam_scope=None)
    if "files" in excluded_sources:
        selected.pop("files", None)
    return selected
