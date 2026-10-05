"""Exact-phrase statistics and matching; no database writes or model calls."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.app.ai.context.adaptive import settings
from backend.app.ai.context.adaptive.store import clean_text
from backend.app.ai.context.contracts import ContextSelection
from backend.app.ai.context.adaptive.contracts import PatternApproval


def normalize_request(text):
    text = text.casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w\s']", " ", text).split())


def profile_key(selection):
    profile = ContextSelection.model_validate(selection).model_dump()
    return json.dumps(profile, sort_keys=True, separators=(",", ":"))


def pattern_id(pattern):
    return hashlib.sha256(pattern.encode()).hexdigest()


def compile_patterns(records, *, states=None, now=None):
    """Only complete explicit labels count. Recompute after sharing/review changes."""
    now = now or datetime.now(timezone.utc)
    groups = defaultdict(list)
    seen = set()
    for row in records:
        event, label = row["event"], row["label"]
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        stamp = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        if (label is None or not label.complete or event.context_dependent
                or event.schema_version != settings.SCHEMA_VERSION or event.router_version != settings.ROUTER_VERSION
                or not now - timedelta(days=settings.EVIDENCE_MAX_DAYS) <= stamp <= now):
            continue
        groups[event.pattern].append(row)
    result = []
    for pattern, rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda row: (datetime.fromisoformat(row["event"].timestamp), row["event"].event_id), reverse=True)[:settings.EVIDENCE_WINDOW]
        counts = Counter(profile_key(row["label"].selection) for row in rows)
        profile, agreement_count = counts.most_common(1)[0]
        selected_profile = json.loads(profile)
        count = len(rows)
        agreement = agreement_count / count
        days = len({datetime.fromisoformat(row["event"].timestamp).date() for row in rows})
        last = max(datetime.fromisoformat(row["event"].timestamp) for row in rows)
        eligible = (count >= settings.MIN_CONFIRMED_SAMPLES and agreement >= settings.PROMOTION_AGREEMENT
                    and days >= settings.MIN_EVIDENCE_DAYS and now - last <= timedelta(days=settings.STALE_AFTER_DAYS)
                    and selected_profile["memory"] is None and selected_profile.get("files") is None)
        # Memory outcomes are evidence, although V1 cannot activate memory shortcuts.
        identifier = pattern_id(pattern)
        raw_state = (states or {}).get(identifier)
        state = PatternApproval.model_validate(raw_state) if raw_state else None
        # Cached decisions never substitute for freshly eligible evidence.
        suspended = bool(state and (state.suspended or state.schema_version != settings.SCHEMA_VERSION
                                   or state.router_version != settings.ROUTER_VERSION
                                   or profile_key(state.selection) != profile))
        if state:
            suspended |= any(row["label_id"] not in state.approved_label_ids
                             and profile_key(row["label"].selection) != profile_key(state.selection) for row in rows)
        result.append({"pattern_id": identifier, "pattern": pattern,
                       "selection": selected_profile, "confirmed_count": count,
                       "agreement_count": agreement_count, "agreement": agreement,
                       "evidence_days": days, "eligible": eligible and not suspended,
                       "state": "suspended" if suspended else "active" if eligible and state else "shadow" if eligible else "candidate",
                       "label_ids": [row["label_id"] for row in rows],
                       "profile_key": profile, "last_confirmed": last.isoformat()})
    return result


def match_pattern(message, patterns, recent_turns=()):
    """Preserve negation and date words; do not generalize or replay old queries."""
    if clean_text(message) != message or len(message) > 600:
        return None
    if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", message):
        return None
    if recent_turns and re.search(r"\b(it|that|those|same|earlier|previously)\b", message.casefold()):
        return None
    pattern = normalize_request(message)
    matches = [item for item in patterns if item.get("pattern") == pattern and item.get("eligible")]
    if len(matches) != 1:
        return None
    candidate = matches[0]
    ContextSelection.model_validate(candidate["selection"])
    return candidate
