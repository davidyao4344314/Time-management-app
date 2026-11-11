"""Recognize completion-record questions without reading planner data."""

import re


def requests_study_history(message):
    text = message.casefold()
    if not re.search(r'\b(my|me|i|our|we)\b|\b(show|list|check|review|which)\b', text):
        return False
    return bool(re.search(
        r'\b(?:study history|study log|session log|completion records?|'
        r'actual (?:study )?(?:minutes|time|hours)|'
        r'(?:completed|finished|missed|partly done|logged|recorded) (?:study |revision )?(?:sessions?|activities|work)|'
        r'(?:sessions?|activities) (?:did i |have i |i )?(?:complete(?:d)?|finish(?:ed)?|miss(?:ed)?)|'
        r'what (?:did|have) i (?:complete(?:d)?|finish(?:ed)?|miss(?:ed)?)|'
        r'how (?:much|many) (?:time|minutes|hours).{0,60}(?:study|studied|spend|spent)|'
        r'(?:study|studying|session|activity) (?:progress|completion))\b', text))


def narrow_study_history_request(message):
    """Mixed requests keep the normal multi-source semantic routing path."""
    return requests_study_history(message) and not re.search(
        r'\b(?:exams?|tests?|deadlines?|quizzes|plan|planning|schedule|calendar|'
        r'tomorrow|next week|remember|discuss|said|chat|conversation|files?|pdf|documents?)\b',
        message.casefold())
