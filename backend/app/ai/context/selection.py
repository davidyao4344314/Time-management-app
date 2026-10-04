"""One-pass Stage 1 → Stage 2 → Stage 3 → safe fallback routing."""

from backend.app.ai.context.keywords import assess_stage_one
from backend.app.ai.context.intent import classify_agent_intent, context_from_classification, CLASSIFIER_VERSION
from backend.app.ai.context.fallback import classify_stage_three
from backend.app.ai.context.contracts import ContextSelection
from backend.app.ai.context.policy import apply_context_exclusions, excluded_context_sources
from backend.app.ai.context.adaptive.patterns import match_pattern, profile_key
from backend.app.ai.context.adaptive.metrics import high_confidence_reliability
from backend.app.ai.context.adaptive.examples import validate_examples, example_version_suffix


SAFE_MINIMAL_CONTEXT = {
    "activities_scope": "today",
    "include_exams": True,
    "exam_scope": "upcoming",
}


def _valid_context_selection(selection):
    """Do not short-circuit on a malformed Stage 1 result."""
    try:
        ContextSelection.model_validate(selection)
        return True
    except ValueError:
        return False


def select_agent_context(client, user_message, recent_turns, stage_two_model, *, trace=None, evidence=None, adaptive_snapshot=None):
    """Stop at the first confident route; never retry a failed stage."""
    excluded = excluded_context_sources(user_message)

    def candidate(stage, status, selected=None, decision=None):
        if evidence is not None:
            parsed = decision.model_dump() if decision is not None else {}
            confidence = parsed.pop("confidence", None)
            evidence.setdefault("candidates", []).append({
                "stage": stage, "status": status, "selection": selected,
                "classification": parsed or None, "confidence": confidence,
            })

    def finish(selected, stage, status, reason, decision=None):
        if evidence is not None:
            evidence["initial_selection"] = apply_context_exclusions(selected, excluded)
        return _record_route(
            trace, apply_context_exclusions(selected, excluded),
            stage, status, reason, decision,
        )

    stage_one = assess_stage_one(user_message, recent_turns)
    if not isinstance(adaptive_snapshot, dict):
        adaptive_snapshot = None
    matched = None
    if adaptive_snapshot and adaptive_snapshot.get("mode") in {"shadow", "active"}:
        try:
            matched = match_pattern(user_message, adaptive_snapshot.get("patterns", []), recent_turns)
            if evidence is not None:
                evidence["adaptive"] = {"mode": adaptive_snapshot["mode"],
                    "pattern_id": matched["pattern_id"] if matched else None,
                    "confirmed_samples": matched["confirmed_count"] if matched else 0,
                    "observed_agreement": matched["agreement"] if matched else None,
                    "shortcut_state": matched["state"] if matched else "no_match", "shortcut_used": False}
        except (ValueError, KeyError, TypeError):
            matched = None
    protected_reasons = {"depends_on_recent_conversation", "conflicting_time_scopes",
                         "mixed_memory_and_current_request", "ambiguous_conversation_reference",
                         "independent_exam_horizon", "negated_calendar_reference", "negated_exam_reference"}
    use_learned = (adaptive_snapshot and adaptive_snapshot.get("mode") == "active" and matched
                   and matched["state"] == "active" and not excluded
                   and stage_one.get("reason") not in protected_reasons)
    learned_reason = None
    if use_learned:
        conflict = stage_one["confident"] and _valid_context_selection(stage_one["selection"]) \
            and profile_key(stage_one["selection"]) != profile_key(matched["selection"])
        if conflict or adaptive_snapshot.get("audit_due"):
            stage_one = {**stage_one, "confident": False,
                         "reason": "learned_rule_conflict" if conflict else "learned_rule_audit"}
            if evidence is not None:
                evidence["adaptive"]["shortcut_state"] = stage_one["reason"]
                evidence["audit_selected"] = bool(adaptive_snapshot.get("audit_due"))
        else:
            stage_one = {"selection": matched["selection"], "confident": True, "reason": None}
            learned_reason = "Matched a reviewed learned phrase with sufficient recent confirmed evidence."
            if evidence is not None:
                evidence["adaptive"]["shortcut_used"] = True
    candidate("stage_1", "matched" if stage_one["confident"] and _valid_context_selection(stage_one["selection"])
              else "unresolved", stage_one.get("selection") if _valid_context_selection(stage_one.get("selection")) else None)
    if stage_one["confident"] and _valid_context_selection(stage_one["selection"]):
        return finish(stage_one["selection"], "stage_1", "matched",
                             learned_reason or "Matched clear keyword/phrase rules.")
    if stage_one["confident"]:
        stage_one = {**stage_one, "confident": False, "reason": "invalid_stage_one_result"}

    try:
        examples = []
        if adaptive_snapshot and adaptive_snapshot.get("mode") == "active" and adaptive_snapshot.get("examples_enabled"):
            try:
                examples = validate_examples(adaptive_snapshot.get("examples", []))
            except ValueError:
                examples = []
        classifier_version = CLASSIFIER_VERSION + example_version_suffix(examples)
        if evidence is not None:
            evidence["classifier_version"] = classifier_version
            evidence.setdefault("adaptive", {})["examples_used"] = len(examples)
        stage_two = classify_agent_intent(
            client, user_message, recent_turns, stage_two_model,
            **({"confirmed_examples": examples} if examples else {}),
        )
        selected = context_from_classification(stage_two)
        ContextSelection.model_validate(selected)
        reliability = {"status": "low_confidence", "escalate": False}
        if stage_two.confidence == "high":
            try:
                reliability = high_confidence_reliability(selected, adaptive_snapshot, stage_two_model, classifier_version)
            except (ValueError, TypeError, KeyError):
                reliability = {"status": "unavailable", "escalate": False}
        if evidence is not None:
            evidence.setdefault("adaptive", {})["calibration"] = reliability
        accepted = stage_two.confidence == "high" and not reliability["escalate"]
        candidate("stage_2", "matched" if accepted else "unresolved", selected, stage_two)
        if accepted:
            return finish(selected, "stage_2", "matched",
                                 "Stage 1 was unresolved; Stage 2 returned a high-confidence classification.", stage_two)
        stage_two_result = {
            "classification": stage_two.model_dump(),
            "reason": "reviewed_reliability_low" if reliability["escalate"] else "low_confidence",
        }
    except Exception:
        if evidence is not None and not any(item["stage"] == "stage_2" for item in evidence.get("candidates", [])):
            candidate("stage_2", "unavailable")
        stage_two_result = {
            "classification": None,
            "reason": "invalid_or_unavailable",
        }

    try:
        decision = classify_stage_three(
            client, user_message, recent_turns, stage_one, stage_two_result,
        )
        selected = context_from_classification(decision)
        candidate("stage_3", "matched", selected, decision)
        return finish(selected, "stage_3", "matched",
                             "Earlier stages were unresolved; Stage 3 returned a valid classification.", decision)
    except Exception:
        candidate("stage_3", "unavailable")
        candidate("safe_fallback", "fallback", SAFE_MINIMAL_CONTEXT.copy())
        return finish(SAFE_MINIMAL_CONTEXT.copy(), "safe_fallback", "fallback",
                             "No confident valid route was available; the existing minimal context was selected.")


def _record_route(trace, selected, stage, status, reason, decision=None):
    """Copy public facts only; never expose classifier scratchpads or prompts."""
    if trace is not None:
        decision = decision.model_dump() if hasattr(decision, "model_dump") else (decision or {})
        trace.update({
            "stage": stage,
            "label": {"stage_1": "Stage 1 — Keyword/Phrase Router",
                      "stage_2": "Stage 2 — Semantic Intent Classifier",
                      "stage_3": "Stage 3 — Fallback Router",
                      "safe_fallback": "Safe minimal fallback"}[stage],
            "status": status,
            # Stage 1 does not classify intent: don't fabricate one for the UI.
            "intent": decision.get("intent"),
            "time_scope": decision.get("time_scope") or selected.get("activities_scope")
                          or selected.get("exam_scope")
                          or (selected.get("memory") or {}).get("query", {}).get("time_reference"),
            "reason": reason,
            "activities_scope": selected.get("activities_scope"),
            "exam_scope": selected.get("exam_scope"),
        })
    return selected
