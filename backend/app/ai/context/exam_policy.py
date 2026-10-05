"""Small assessment-subset policy, separate from whole-source routing."""

import re


def explicit_exam_filter(message):
    """Recognize a formal-exam restriction, or an explicit return to assessments."""
    text = message.casefold().replace("’", "'")
    formal = r"\b(?:only\s+(?:(?:the|my|formal|final)\s+)*exams?|exams?\s+only|(?:formal|final)\s+exams?)\b"
    if re.search(r"\b(?:not|don't|do not)\s+only\s+(?:(?:the|my)\s+)*exams?\b", text):
        return "all"
    if re.search(formal, text):
        return "formal_exams"
    for match in re.finditer(r"\b(?:show|list|include|what|which|how|plan for|what about)\b[^.!?]{0,60}\b(?:quiz|quizzes|tests?|assignments?|assessments?|labs?)\b", text):
        if not re.search(r"\b(?:don't|dont|do not|never)\s+$", text[:match.start()]):
            return "all"
    return None


def choose_exam_filter(user_message, recent_turns=None):
    """Current explicit choices override the latest bounded user conversation.

    Assistant statements cannot set this policy. No preferences are persisted.
    """
    for message in [user_message, *(turn["user"] for turn in reversed(list(recent_turns or [])))]:
        selected = explicit_exam_filter(message)
        if selected is not None:
            return selected
    return "all"
