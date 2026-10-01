"""Read-only, rule-based protection labels for Stage 2 archive candidates."""

import re
from copy import deepcopy


# These phrases signal an explicit instruction, durable goal, or decision.
# A weak single word such as "goal" or "important" never protects a turn.
STRONG_PROTECTION_RULES = (
    ("remember this", "explicit_memory"),
    ("remember that", "explicit_memory"),
    ("save this", "explicit_memory"),
    ("store this", "explicit_memory"),
    ("from now on", "preference"),
    ("going forward", "preference"),
    ("my long-term goal", "goal"),
    ("my goal is", "goal"),
    ("we decided", "decision"),
    ("we agreed", "decision"),
    ("this is a requirement", "requirement"),
    ("must keep", "constraint"),
    ("do not change", "constraint"),
    ("don't change", "constraint"),
    ("always do", "constraint"),
    ("never do", "constraint"),
    ("important decision", "decision"),
    ("project requirement", "requirement"),
    ("my long-term plan", "long_term_plan"),
)

WEAK_RULES = (
    "i want to",
    "important",
    "goal",
    "plan",
    "deadline",
    "maybe",
    "later",
)

# Only plain, short-lived question shapes are marked compactable. Other
# unmatched turns remain uncertain for a later protection stage.
ORDINARY_QUESTION_RULES = (
    ("can you explain", re.compile(r"^\s*can you explain\b")),
    ("what is", re.compile(r"^\s*what (?:is|are|does|do)\b")),
    ("why is", re.compile(r"^\s*why (?:is|does|did)\b")),
    ("how do", re.compile(r"^\s*how (?:do|does|can)\b")),
)


def _phrase_pattern(phrase):
    return re.compile(r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)")


_STRONG_PATTERNS = tuple(
    (phrase, category, _phrase_pattern(phrase))
    for phrase, category in STRONG_PROTECTION_RULES
)
_WEAK_PATTERNS = tuple((phrase, _phrase_pattern(phrase)) for phrase in WEAK_RULES)


def _turn_texts(candidate):
    """Get user and assistant text, excluding proposed action arguments."""
    turn = candidate["turn"]
    assistant = turn.get("assistant")
    if isinstance(assistant, dict):
        assistant = assistant.get("message")
    return tuple(
        text.casefold().replace("’", "'")
        for text in (turn.get("user"), assistant)
        if isinstance(text, str)
    )


def classify_archive_candidate(candidate):
    """Label one complete archived turn without changing its stored record."""
    if not isinstance(candidate, dict) or not isinstance(candidate.get("turn"), dict):
        raise ValueError("A Stage 2 archived-turn record is required.")

    texts = _turn_texts(candidate)
    status, category, matched_rule = "uncertain", None, None

    for phrase, rule_category, pattern in _STRONG_PATTERNS:
        if any(pattern.search(text) for text in texts):
            status, category, matched_rule = "protected", rule_category, phrase
            break
    else:
        for phrase, pattern in _WEAK_PATTERNS:
            if any(pattern.search(text) for text in texts):
                matched_rule = phrase
                break
        else:
            user = candidate["turn"].get("user")
            if isinstance(user, str):
                user = user.casefold().replace("’", "'")
                for phrase, pattern in ORDINARY_QUESTION_RULES:
                    if pattern.search(user):
                        status, matched_rule = "compactable", phrase
                        break

    return {
        "status": status,
        "category": category,
        "matched_rule": matched_rule,
        "archived_turn": deepcopy(candidate),
    }


def classify_compaction_candidates(candidates):
    """Group only the supplied Stage 2 candidates, keeping their order."""
    if isinstance(candidates, dict):
        raise ValueError("Pass the Stage 2 compaction_candidates list, not its result object.")

    groups = {"protected": [], "compactable": [], "uncertain": []}
    for candidate in candidates:
        result = classify_archive_candidate(candidate)
        groups[result["status"]].append(result)

    return {
        "candidate_count": sum(len(group) for group in groups.values()),
        "protected_count": len(groups["protected"]),
        "compactable_count": len(groups["compactable"]),
        "uncertain_count": len(groups["uncertain"]),
        **groups,
    }
