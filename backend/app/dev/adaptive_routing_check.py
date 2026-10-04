"""Offline adaptive-routing wiring check with synthetic reviews and a fake model.

Does not open a database, archive or .env, and cannot make paid API calls.
This checks routing safeguards, not real semantic classifier quality.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.ai.context.adaptive.contracts import RoutingEvent, RoutingLabel, PatternApproval
from backend.app.ai.context.adaptive.patterns import compile_patterns, pattern_id, profile_key
from backend.app.ai.context.contracts import AgentIntentClassification
from backend.app.ai.context.selection import select_agent_context

PHRASE = "Can I fit another task around my commitments?"
PROFILE = {"activities_scope": "today", "include_exams": False, "exam_scope": None}


def synthetic_patterns(now):
    rows = []
    for index in range(30):
        event = RoutingEvent(event_id=str(index), owner_id="synthetic-owner", conversation_id="synthetic-chat",
            request_id=str(index), timestamp=(now - timedelta(days=index % 3)).isoformat(),
            classifier_model="offline-fake", classifier_version="synthetic-v1", pattern=PHRASE.lower().rstrip("?"),
            request_excerpt=PHRASE, candidates=[], initial_selection=PROFILE, final_selection=PROFILE,
            initial_status={}, final_status={})
        label = RoutingLabel(signal="developer", status="confirmed", selection=PROFILE,
            confirmed_fields=["activities_scope", "include_exams", "exam_scope", "memory"])
        rows.append({"event": event, "label": label, "label_id": str(index)})
    identifier = pattern_id(rows[0]["event"].pattern)
    approval = PatternApproval(selection=PROFILE, approved_label_ids=[row["label_id"] for row in rows], shadow_reviewed=True)
    return compile_patterns(rows, now=now, states={identifier: approval.model_dump()})


class FakeClient:
    def __init__(self, classification):
        self.responses = self
        self.classification = classification
        self.calls = 0

    def parse(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(status="completed", output_parsed=self.classification)


def evaluate():
    now = datetime.now(timezone.utc)
    patterns = synthetic_patterns(now)
    default = AgentIntentClassification(intent="schedule_query", time_scope="today",
        include_activities=True, include_exams=False, confidence="high")
    cases = [
        ("exact reviewed phrase", PHRASE, default, False, []),
        ("capitalization and punctuation", PHRASE.upper().rstrip("?") + "!", default, False, []),
        ("different wording", "Could I fit another task around my commitments?", default, False, []),
        ("source exclusion", "Don't use my calendar. " + PHRASE,
         AgentIntentClassification(intent="general_question", time_scope="unspecified", include_activities=False,
                                   include_exams=False, confidence="high"), False, []),
        ("new time scope", "Can I fit another task around my commitments tomorrow?",
         AgentIntentClassification(intent="schedule_query", time_scope="tomorrow", include_activities=True,
                                   include_exams=False, confidence="high"), False, []),
        ("optional audit", PHRASE, default, True, []),
        ("recent follow-up", "Make it later.", default, False,
         [{"user": PHRASE, "assistant": {"message": "Consider an evening slot."}}]),
    ]
    results = []
    for name, message, decision, audit, recent in cases:
        mode_results = []
        expected = {"activities_scope": decision.time_scope if decision.include_activities else None,
                    "include_exams": decision.include_exams, "exam_scope": None}
        for mode in ("off", "shadow", "active"):
            client, trace, evidence = FakeClient(decision), {}, {}
            selected = select_agent_context(client, message, recent, "offline-fake", trace=trace, evidence=evidence,
                adaptive_snapshot={"mode": mode, "patterns": patterns, "audit_due": audit})
            expected_shortcut = mode == "active" and name in {"exact reviewed phrase", "capitalization and punctuation"}
            matched = profile_key(selected) == profile_key(expected)
            shortcut_ok = bool(evidence.get("adaptive", {}).get("shortcut_used")) == expected_shortcut
            mode_results.append({"mode": mode, "stage": trace["stage"], "classifier_calls": client.calls,
                                 "selection": selected, "passed": matched and shortcut_ok})
        results.append({"case": name, "runs": mode_results})
    return {"mode": "offline synthetic wiring check; no paid calls or real learning data",
            "cases": results, "passed": all(run["passed"] for case in results for run in case["runs"])}


def main():
    report = evaluate()
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
