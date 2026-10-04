"""Turn completed routing telemetry into unconfirmed, bounded evidence."""

from uuid import NAMESPACE_URL, uuid5
from backend.app.ai.context.adaptive.contracts import RoutingEvent, RoutingLabel
from backend.app.ai.context.adaptive import store
from backend.app.ai.context.intent import CLASSIFIER_VERSION, context_from_classification
from backend.app.ai.context.contracts import ContextSelection
from backend.app.ai.context.policy import apply_context_exclusions
from backend.app.ai.context.adaptive.patterns import normalize_request, compile_patterns


def load_snapshot(connection, owner_id, conversation_id, adaptive_settings):
    records = store.load_eligible_evidence(connection, owner_id, conversation_id)
    states = store.load_pattern_states(connection, owner_id, conversation_id)
    return {"mode": adaptive_settings.mode,
            "patterns": compile_patterns(records, states=states),
            "examples_enabled": adaptive_settings.examples_enabled,
            "calibration_enabled": adaptive_settings.calibration_enabled,
            "audit_due": False}


def make_completed_event(owner_id, conversation_id, request_id, message, evidence):
    """Model disagreement and recovery remain observations, not confirmations."""
    clean = store.clean_text(message)
    pattern = normalize_request(clean)
    return RoutingEvent.model_validate({
        "event_id": str(uuid5(NAMESPACE_URL, f"{owner_id}:{conversation_id}:{request_id}")),
        "owner_id": owner_id, "conversation_id": conversation_id, "request_id": request_id,
        "timestamp": store.now_iso(), "classifier_model": evidence["classifier_model"],
        "classifier_version": evidence.get("classifier_version", CLASSIFIER_VERSION),
        "pattern": pattern[:600], "request_excerpt": clean[:600],
        "context_dependent": bool(evidence.get("context_dependent")) or len(clean) > 600 or clean != message,
        "candidates": evidence.get("candidates", []),
        "initial_selection": evidence["initial_selection"], "final_selection": evidence["final_selection"],
        "initial_status": evidence["initial_status"], "final_status": evidence["final_status"],
        "excluded_sources": evidence.get("excluded_sources", []),
        "recovery_requested": evidence.get("recovery_requested", False),
        "recovery_completed": evidence.get("recovery_completed", False),
        "audit_selected": evidence.get("audit_selected", False),
    })


def apply_reviewed_label(connection, owner_id, event_id, value):
    """Local explicit review only. No model prediction can invoke this path."""
    event = store.event_by_id(connection, owner_id, event_id)
    label = RoutingLabel.model_validate(value)
    guarded = ContextSelection.model_validate(apply_context_exclusions(
        label.selection.model_dump(), event.excluded_sources))
    if guarded != label.selection:
        raise ValueError("A reviewed route cannot override the request's source exclusions.")
    if label.classification is not None:
        converted = ContextSelection.model_validate(context_from_classification(label.classification.model_dump()))
        if converted != label.selection:
            raise ValueError("Reviewed classification and context selection must agree.")
    if label.example_approved and (event.context_dependent or not event.request_excerpt):
        raise ValueError("Examples must be bounded self-contained requests.")
    return store.record_label(connection, owner_id, event_id, label.model_dump())
