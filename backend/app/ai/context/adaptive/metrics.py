"""Observed routing agreement, not model probabilities or automatic labels."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.app.ai.context.adaptive import settings
from backend.app.ai.context.adaptive.patterns import profile_key
from backend.app.ai.context.contracts import ContextSelection


def source_family(selection):
    selected = ContextSelection.model_validate(selection)
    return "+".join(name for name, enabled in (
        ("activities", selected.activities_scope is not None), ("exams", selected.include_exams),
        ("memory", selected.memory is not None)) if enabled) or "none"


def summarize_reliability(records, *, now=None):
    now = now or datetime.now(timezone.utc)
    groups, fields, intents = defaultdict(list), defaultdict(Counter), Counter()
    seen, reviewed = set(), 0
    recovery_requests, audits = 0, 0
    for row in records:
        event, label = row["event"], row["label"]
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        stamp = datetime.fromisoformat(event.timestamp)
        if (event.schema_version != settings.SCHEMA_VERSION or event.router_version != settings.ROUTER_VERSION
                or not now - timedelta(days=settings.EVIDENCE_MAX_DAYS) <= stamp <= now):
            continue
        recovery_requests += int(event.recovery_requested)
        audits += int(event.audit_selected)
        if label is None or label.status != "confirmed":
            continue
        candidate = next((item for item in event.candidates if item.stage == "stage_2"), None)
        if candidate is None or candidate.selection is None:
            continue
        reviewed += 1
        predicted, expected = candidate.selection.model_dump(), label.selection.model_dump()
        for field in label.confirmed_fields:
            result = "correct" if predicted[field] == expected[field] else "incorrect"
            fields[field][result] += 1
            if field == "include_exams" and result == "incorrect":
                fields[field]["false_positive" if predicted[field] else "false_negative"] += 1
            if field in {"activities_scope", "memory"} and result == "incorrect":
                if predicted[field] is None:
                    fields[field]["false_negative"] += 1
                elif expected[field] is None:
                    fields[field]["false_positive"] += 1
                else:
                    fields[field]["wrong_scope"] += 1
        if label.classification is not None and candidate.classification is not None:
            intents[(candidate.classification.intent, label.classification.intent)] += 1
        if label.complete and candidate.confidence is not None:
            key = (event.classifier_model, event.classifier_version,
                   source_family(candidate.selection), candidate.confidence)
            groups[key].append((stamp, event.event_id, profile_key(predicted) == profile_key(expected)))
    buckets = []
    for (model, version, family, confidence), values in sorted(groups.items()):
        values = sorted(values, reverse=True)[:settings.EVIDENCE_WINDOW]
        count, correct = len(values), sum(item[2] for item in values)
        buckets.append({"model": model, "version": version, "family": family, "confidence": confidence,
                        "confirmed_count": count, "correct_count": correct,
                        "observed_agreement": correct / count,
                        "sufficient_evidence": count >= settings.MIN_CALIBRATION_SAMPLES})
    return {"buckets": buckets, "field_results": {key: dict(value) for key, value in sorted(fields.items())},
            "intent_confusions": [{"predicted": pair[0], "confirmed": pair[1], "count": count}
                                  for pair, count in sorted(intents.items())],
            "reviewed_stage_two": reviewed,
            "operational_signals": {"recovery_requests": recovery_requests, "audits": audits}}


def high_confidence_reliability(selection, snapshot, model, version):
    """Calibration may only escalate high confidence, never promote low confidence."""
    default = {"status": "disabled", "escalate": False, "confirmed_count": 0, "observed_agreement": None}
    if not snapshot or snapshot.get("mode") != "active" or not snapshot.get("calibration_enabled"):
        return default
    default["status"] = "insufficient_evidence"
    for bucket in snapshot.get("reliability", {}).get("buckets", []):
        if (bucket["model"], bucket["version"], bucket["family"], bucket["confidence"]) == (
                model, version, source_family(selection), "high"):
            if (type(bucket["confirmed_count"]) is not int or type(bucket["observed_agreement"]) not in {float, int}
                    or not 0 <= bucket["observed_agreement"] <= 1):
                raise ValueError("Invalid calibration statistics.")
            sufficient = bucket["confirmed_count"] >= settings.MIN_CALIBRATION_SAMPLES
            escalate = sufficient and bucket["observed_agreement"] < settings.MIN_HIGH_CONFIDENCE_AGREEMENT
            return {"status": "escalated" if escalate else "accepted" if sufficient else "insufficient_evidence",
                    "escalate": escalate, "confirmed_count": bucket["confirmed_count"],
                    "observed_agreement": bucket["observed_agreement"]}
    return default
