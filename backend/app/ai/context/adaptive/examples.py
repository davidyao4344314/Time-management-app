"""Small, explicitly reviewed routing examples; no observations or model calls."""

import json
import hashlib
import re
from datetime import datetime, timedelta, timezone

from backend.app.ai.context.adaptive import settings
from backend.app.ai.context.adaptive.patterns import normalize_request, profile_key
from backend.app.ai.context.contracts import AgentRoutingDecision
from backend.app.ai.context.profiles import context_from_classification

EXAMPLE_POLICY_VERSION = "reviewed-examples-v1"
STOP_WORDS = frozenset("a an and are as at be can do for from have help i in is it me my of on or should that the this to what when with you your".split())


def example_version_suffix(examples):
    if not examples:
        return ""
    fingerprint = hashlib.sha256(json.dumps(examples, sort_keys=True).encode()).hexdigest()[:8]
    return "+" + EXAMPLE_POLICY_VERSION + ":" + fingerprint


def topic_tokens(text):
    return set(re.findall(r"\w+", normalize_request(text))) - STOP_WORDS


def validate_examples(examples):
    """Validate again at the model boundary; budget covers complete JSON examples."""
    if not isinstance(examples, list) or len(examples) > settings.MAX_EXAMPLES:
        raise ValueError("Too many routing examples.")
    clean, size = [], 0
    for value in examples:
        if not isinstance(value, dict) or set(value) != {"request", "classification"}:
            raise ValueError("Unexpected routing example fields.")
        request = value["request"]
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Routing examples require a request.")
        classification = AgentRoutingDecision.model_validate(value["classification"])
        example = {"request": request, "classification": classification.model_dump()}
        length = len(json.dumps(example, ensure_ascii=False))
        size += length
        if length > settings.MAX_EXAMPLE_CHARS or size > settings.MAX_EXAMPLES_CHARS:
            raise ValueError("Routing example budget exceeded.")
        clean.append(example)
    return clean


def select_examples(records, message, *, now=None):
    now = now or datetime.now(timezone.utc)
    tokens = topic_tokens(message)
    if not tokens:
        return []
    candidates, outcomes = [], {}
    for row in records:
        event, label = row["event"], row["label"]
        stamp = datetime.fromisoformat(event.timestamp)
        if (label is None or not label.example_approved or not label.complete
                or label.classification is None or event.context_dependent or not event.request_excerpt
                or event.schema_version != settings.SCHEMA_VERSION or event.router_version != settings.ROUTER_VERSION
                or not now - timedelta(days=settings.EVIDENCE_MAX_DAYS) <= stamp <= now):
            continue
        if profile_key(context_from_classification(label.classification)) != profile_key(label.selection):
            continue
        key = normalize_request(event.request_excerpt)
        outcomes.setdefault(key, set()).add(profile_key(label.selection))
        overlap = tokens & topic_tokens(event.request_excerpt)
        if not overlap:
            continue
        example = {"request": event.request_excerpt, "classification": label.classification.model_dump()}
        try:
            validate_examples([example])
        except ValueError:
            continue
        candidates.append((len(overlap), stamp, key, example))
    result, seen = [], set()
    for _, _, key, example in sorted(candidates, key=lambda item: (item[0], item[1], item[2]), reverse=True):
        if key in seen or len(outcomes[key]) != 1:
            continue  # Ambiguous reviewed outcomes are not teaching examples.
        seen.add(key)
        if len(result) >= settings.MAX_EXAMPLES:
            break
        try:
            validate_examples(result + [example])
        except ValueError:
            continue
        result.append(example)
    return result
