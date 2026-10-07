"""Bounded literal activity-ID references; no guessing or database access."""
import re

MAX_REQUESTED_ACTIVITY_IDS = 3
_ACTIVITY_ID = re.compile(r'\bactivity\s+(?:id\s*[:=]?\s*)?#?\s*([1-9]\d{0,18})\b', re.IGNORECASE)


def requested_activity_ids(message):
    identifiers = []
    for match in _ACTIVITY_ID.finditer(message):
        identifier = int(match.group(1))
        if identifier <= 2**63-1 and identifier not in identifiers:
            identifiers.append(identifier)
        if len(identifiers) == MAX_REQUESTED_ACTIVITY_IDS:
            break
    return identifiers
