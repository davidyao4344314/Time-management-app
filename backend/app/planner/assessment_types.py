"""Conservative assessment labels for existing records, without rewriting rows."""

import re


def classify_assessment_name(name):
    """Use explicit labels only; an exam table row is not necessarily an exam.

    Source and category are not evidence of assessment type. Ambiguous names
    remain unknown. Preparation/quiz/assignment labels take precedence over
    'exam', e.g. 'Lab20 - Exam Revision' is not a formal exam.
    """
    if not isinstance(name, str):
        return "unknown"
    text = name.casefold()
    for kind, pattern in (
        ("quiz", r"\b(?:quiz|quizzes)\b"),
        ("assignment", r"\bassignments?\b|\bcoursework\b"),
        ("preparation", r"\blab\d*\b|\blaborator(?:y|ies)\b|\btutorials?\b|\brevision\b|\bpractice\b|\bmock\b"),
        ("test", r"\btests?\b"),
        ("exam", r"\bexams?\b|\bexaminations?\b"),
    ):
        if re.search(pattern, text):
            return kind
    return "unknown"
