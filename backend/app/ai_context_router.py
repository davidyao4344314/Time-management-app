"""Choose compact agent observations using only the user's words."""

import re


TODAY_PHRASES = (
    "today", "tonight", "this evening", "this afternoon", "this morning",
    "later today", "today's",
)
WEEK_PHRASES = ("this week", "week", "next few days", "upcoming week")
MONTH_PHRASES = ("this month", "month", "rest of the month", "later this month")
EXAM_WORDS = (
    "exam", "exams", "test", "tests", "assessment", "assessments",
    "deadline", "deadlines", "quiz", "quizzes",
)
ALL_ACTIVITY_PHRASES = (
    "all activities", "everything on my calendar", "full calendar",
    "all my activities", "entire schedule", "whole schedule",
)
ALL_CONTEXT_PHRASES = (
    "everything", "all my information", "all activities and exams",
    "full study plan", "look at everything",
)
STUDY_WORDS = ("study", "studying", "revision", "revise", "plan", "planning")


def _has_phrase(message, phrases):
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", message)
        for phrase in phrases
    )


def choose_agent_context(user_message):
    """Return activity scope and exam scope, without reading data or calling an LLM.

    An exam-only question can omit activities while retaining its time scope.
    The default is deliberately small: today's activities and upcoming exams.
    """
    message = user_message.casefold().replace("’", "'")
    asks_exams = _has_phrase(message, EXAM_WORDS)
    asks_all_activities = _has_phrase(message, ALL_ACTIVITY_PHRASES)
    asks_everything = _has_phrase(message, ALL_CONTEXT_PHRASES)

    if asks_all_activities or asks_everything:
        # "Everything on my calendar" means activities, not every data source.
        include_exams = asks_exams or (asks_everything and not asks_all_activities)
        return {
            "activities_scope": "all",
            "include_exams": include_exams,
            "exam_scope": "upcoming" if include_exams else None,
        }

    if _has_phrase(message, MONTH_PHRASES):
        time_scope = "month"
    elif _has_phrase(message, WEEK_PHRASES):
        time_scope = "week"
    elif _has_phrase(message, TODAY_PHRASES):
        time_scope = "today"
    else:
        time_scope = None

    if asks_exams and time_scope is None:
        activities_scope = None
    elif asks_exams and time_scope in {"week", "month"} and not _has_phrase(message, STUDY_WORDS):
        activities_scope = None
    else:
        activities_scope = time_scope or "today"

    include_exams = asks_exams or time_scope is None or _has_phrase(message, STUDY_WORDS)
    exam_scope = (
        time_scope if asks_exams and time_scope in {"week", "month"}
        else "upcoming"
    ) if include_exams else None

    return {
        "activities_scope": activities_scope,
        "include_exams": include_exams,
        "exam_scope": exam_scope,
    }
