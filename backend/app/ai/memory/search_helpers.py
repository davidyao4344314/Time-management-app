"""Pure matching and literal excerpts shared by local and global retrieval."""
from datetime import datetime

MAX_TEXT_CHARS = 600


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None and timestamp.utcoffset() is not None else None


def excerpt(text, terms):
    if len(text) <= MAX_TEXT_CHARS:
        return text
    folded = text.casefold()
    matches = [folded.find(term.casefold()) for term in terms if term.casefold() in folded]
    start = max(0, min(matches) - 100) if matches else 0
    start = min(start, len(text) - MAX_TEXT_CHARS)
    end = start + MAX_TEXT_CHARS
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


def keyword_score(texts, terms, *, weights=None):
    weights = weights or [1] * len(texts)
    return sum(weight * text.casefold().count(term.casefold())
               for text, weight in zip(texts, weights) for term in terms)
