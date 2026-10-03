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
    if re.search(r"\bwhat did i just say\b", message):
        return {"activities_scope": None, "include_exams": False, "exam_scope": None}
    memory = _memory_selection(message)
    if memory is not None and not _mixed_memory_request(message):
        return {"activities_scope": None, "include_exams": False,
                "exam_scope": None, "memory": memory}
    asks_exams = _has_phrase(message, EXAM_WORDS)
    asks_study = _has_phrase(message, STUDY_WORDS) or (
        asks_exams and _has_phrase(message, ("what should i do",))
    )
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
    elif asks_exams and time_scope in {"today", "week", "month"} and not asks_study:
        activities_scope = None
    else:
        activities_scope = time_scope or "today"

    include_exams = asks_exams or time_scope is None or _has_phrase(message, STUDY_WORDS)
    exam_scope = (
        time_scope if asks_exams and time_scope in {"week", "month"}
        or (asks_exams and time_scope == "today" and activities_scope is None)
        else "upcoming"
    ) if include_exams else None

    return {
        "activities_scope": activities_scope,
        "include_exams": include_exams,
        "exam_scope": exam_scope,
    }


def assess_stage_one(user_message, recent_turns=None):
    """Keep the keyword router, but distinguish a clear match from its default."""
    message = user_message.casefold().replace("’", "'")
    selection = choose_agent_context(user_message)
    if re.search(r"\bwhat did i just say\b", message):
        return {"selection": selection, "confident": True, "reason": None}
    phrase_groups = (
        TODAY_PHRASES, WEEK_PHRASES, MONTH_PHRASES, EXAM_WORDS,
        ALL_ACTIVITY_PHRASES, ALL_CONTEXT_PHRASES, STUDY_WORDS,
    )
    if _memory_selection(message) is not None and _mixed_memory_request(message):
        reason = "mixed_memory_and_current_request"
    elif selection.get("memory") is not None:
        reason = None
    elif any(_has_phrase(message, phrases) for phrases in
             (("remember", "previously", "earlier", "last time", "we discussed", "we decided"),)):
        reason = "ambiguous_conversation_reference"
    elif not any(_has_phrase(message, phrases) for phrases in phrase_groups):
        reason = "no_meaningful_keyword_match"
    elif re.search(
        r"\b(?:don't|do not|not|without|exclude|skip)\b[^.!?]{0,80}"
        r"\b(?:exam|exams|test|tests|assessment|assessments|quiz|quizzes)\b",
        message,
    ):
        reason = "negated_exam_reference"
    elif sum(bool(_has_phrase(message, phrases)) for phrases in
             (TODAY_PHRASES, WEEK_PHRASES, MONTH_PHRASES)) > 1:
        reason = "conflicting_time_scopes"
    elif recent_turns and re.search(r"\b(?:it|that|those|same|other stuff)\b", message):
        reason = "depends_on_recent_conversation"
    else:
        reason = None

    return {
        "selection": selection,
        "confident": reason is None,
        "reason": reason,
    }


def _mixed_memory_request(message):
    return bool(re.search(r"\b(help me|based on|use .+ to|and (?:what|help|plan|show))\b", message))


def _memory_selection(message):
    """Recognize explicit recollection, not ordinary 'before dinner' scheduling."""
    if re.search(r"\b(don't|do not|without|ignore)\b.*\b(memory|memories|history|archive)\b", message):
        return None
    historical = re.search(
        r"\b(what did (?:we|i) (?:say|discuss|talk|decide|agree|mention)|what (?:was|were) .*(?:discussed|decided|said)|"
        r"(?:we|i) (?:discussed|decided|said|talked)|remember what|"
        r"(?:my|our) (?:preferences|previous decisions)|remember my preference|earlier in this chat)\b", message)
    if not historical:
        return None
    reference = next((label for phrase, label in (
        ("last week", "last_week"), ("this week", "this_week"),
        ("last month", "last_month"), ("this month", "this_month"),
        ("yesterday", "yesterday"), ("today", "today"),
    ) if _has_phrase(message, (phrase,))), None)
    topics = message
    for phrase in ("last week", "this week", "last month", "this month", "last time"):
        topics = topics.replace(phrase, " ")
    stop = set("what did do we i you me my our the a an was were is are have had about on of for to and that this it before earlier previously yesterday today remember discussed discuss decided decide said say talked talk tell please when with".split())
    terms = list(dict.fromkeys(word for word in re.findall(r"[\w]+", topics)
                               if word not in stop))[:5]
    sources = ["raw_archive"] if _has_phrase(message, ("exact words", "verbatim", "quote")) else (
        ["durable", "raw_archive"] if _has_phrase(message, ("prefer", "preferences", "goal", "goals", "decided", "constraints"))
        else ["compressed_archive", "raw_archive"])
    terms = [term for term in terms if term not in {"exact", "words", "verbatim", "quote"}]
    result = {"sources": sources, "query": {"time_reference": reference, "search_terms": terms}}
    if 'in this chat' in message or 'in this conversation' in message:
        result['scope'] = 'current_chat'
    elif 'remember my preference' in message:
        result['scope'] = 'global'
        result['sources'] = ['durable']
    return result
