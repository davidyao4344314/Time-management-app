"""Public request metadata, never model reasoning, prompts or session secrets."""

import re
from copy import deepcopy

from backend.app.infrastructure.privacy import redact_secrets

SOURCE_INFO = {
    "activities": ("Activities", "current"),
    "exams": ("Exams", "current"),
    "files": ("Imported files", "document_evidence"),
    "recent_memory": ("Recent memory", "historical"),
    "raw_archive": ("Raw archive", "historical"),
    "compressed_archive": ("Compressed archive", "historical_summary"),
    "durable": ("Durable memory", "historical"),
    "current_chat": ("Earlier current-chat messages", "historical"),
}


def build_adaptive_metadata(evidence=None, snapshot=None):
    """Only aggregate routing facts; never expose example text, owners or labels."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    data = (evidence or {}).get("adaptive", {})
    data = data if isinstance(data, dict) else {}
    mode = snapshot.get("mode", "observe" if evidence is not None else "off")
    if mode not in {"off", "observe", "shadow", "active"}:
        mode = "off"

    def count(value, maximum):
        return value if type(value) is int and 0 <= value <= maximum else 0

    def agreement(value):
        return value if type(value) in {int, float} and 0 <= value <= 1 else None

    state = data.get("shortcut_state", "disabled" if mode == "off" else "observing" if mode == "observe" else "unavailable")
    if snapshot.get("knowledge_unavailable"):
        state = "unavailable"
    if state not in {"disabled", "observing", "unavailable", "no_match", "active", "shadow", "candidate",
                     "suspended", "learned_rule_conflict", "learned_rule_audit"}:
        state = "unavailable"
    calibration = data.get("calibration", {})
    calibration = calibration if isinstance(calibration, dict) else {}
    status = calibration.get("status", "not_used")
    if status not in {"not_used", "disabled", "low_confidence", "insufficient_evidence", "escalated", "accepted", "unavailable"}:
        status = "unavailable"
    return {"mode": mode, "shortcut_state": state, "shortcut_used": data.get("shortcut_used") is True,
            "confirmed_samples": count(data.get("confirmed_samples"), 100),
            "observed_agreement": agreement(data.get("observed_agreement")),
            "examples_used": count(data.get("examples_used"), 3),
            "audit_selected": (evidence or {}).get("audit_selected") is True,
            "calibration": {"status": status, "confirmed_samples": count(calibration.get("confirmed_count"), 100),
                            "observed_agreement": agreement(calibration.get("observed_agreement"))}}


def _text(value, limit):
    if not isinstance(value, str):
        return None
    cleaned = redact_secrets(value)
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def build_agent_context(routing, selection, recent_count, lookups):
    """Describe actual selection/retrieval; no inference from the user's words."""
    selected_memory = {source for lookup in lookups for source in
                       (['current_chat'] if lookup['result'].get('scope') == 'current_chat' else lookup['sources'])}
    sources = []
    for source, (label, authority) in SOURCE_INFO.items():
        if source == "activities":
            selected = selection.get("activities_scope") is not None
            reason = f"Selected activity scope: {selection.get('activities_scope')}."
        elif source == "exams":
            selected = selection.get("include_exams", False)
            reason = f"Selected exam scope: {selection.get('exam_scope')}."
        elif source == "recent_memory":
            selected = recent_count > 0
            reason = f"Included {recent_count} completed recent conversation turns."
        elif source == "files":
            selected = selection.get("files") is not None
            reason = "Selected bounded excerpts from the owner's managed file store; not an action or memory lookup."
        else:
            selected = source in selected_memory
            reason = "Requested for a bounded historical lookup within the authorized memory scope."
        sources.append({"source": source, "label": label, "selected": selected,
                        "authority": authority,
                        "reason": reason if selected else "Not selected for this request."})

    retrieved, seen = [], {}
    lookup_details = []
    for lookup in lookups:
        result = lookup["result"]
        lookup_details.append({
            "phase": lookup["phase"], "sources": lookup["sources"],
            "scope": result.get('scope', 'legacy_session'),
            "status": result.get("status", "unavailable"),
            "result_count": len(result.get("items", [])),
            "truncated": bool(result.get("truncated", False)),
            "unavailable_sources": list(result.get("unavailable_sources", [])),
            "used_in_model": lookup["used_in_model"],
        })
        for item in result.get("items", []):
            identity = (item.get("source"), item.get("id"))
            if identity in seen:
                seen[identity]["used_in_model"] |= lookup["used_in_model"]
                continue
            source = item.get("source")
            label, authority = SOURCE_INFO.get(source, ("Historical memory", "historical"))
            public = {
                "source_type": source, "label": label, "authority": authority,
                "conversation_id": _text(item.get('conversation_id'), 80),
                "category": _text(item.get("type") or item.get("category"), 80),
                "excerpt": _text(item.get("text"), 240),
                "source_id": _text(item.get("id"), 128),
                "timestamp": _text(item.get("timestamp"), 80),
                "period_start": _text(item.get("period_start"), 80),
                "period_end": _text(item.get("period_end"), 80),
                "source_refs": [_text(ref, 128) for ref in item.get("source_refs", [])[:5]],
                "time_match": _text(item.get("time_match"), 40),
                "used_in_model": lookup["used_in_model"],
                "reason": "Returned by the selected, bounded memory search.",
            }
            seen[identity] = public
            retrieved.append(public)

    if retrieved:
        noun = "excerpt" if len(retrieved) == 1 else "excerpts"
        memory_message = f"Retrieved {len(retrieved)} compact historical {noun}."
    elif not lookups:
        memory_message = "Historical memory was not requested."
    elif any(lookup["status"] in {"partial", "unavailable"} for lookup in lookup_details):
        memory_message = "Historical memory could not be fully retrieved; no matching excerpts are available."
    else:
        memory_message = "No matching historical memory was found."
    return {
        "routing": dict(routing), "context_sources": sources,
        "retrieved_memory": retrieved, "memory_lookups": lookup_details,
        "memory_message": memory_message,
        "authority_note": "Current app observations take priority over historical memory for current state.",
    }


def record_routing_outcome(routing_evidence, *, classifier_model, selection, initial_status,
                           context_status, excluded_sources, target_ids, recent_turns,
                           user_request, recovery_trace, memory_requested):
    """Record private routing evidence separately from the public inspector."""
    if routing_evidence is not None:
        routing_evidence.update(
            classifier_model=classifier_model,
            final_selection=deepcopy(selection), initial_status=initial_status, final_status=context_status,
            excluded_sources=sorted(excluded_sources),
            context_dependent=bool(
                target_ids or selection.get("files") or (recent_turns and re.search(
                    r"\b(it|that|those|same|earlier|previously)\b", user_request.casefold(),
                ))
            ),
            recovery_requested=bool(recovery_trace["attempts"] or memory_requested),
            recovery_completed=recovery_trace["status"] == "completed",
        )


def build_proposal_context(*, routing_trace, selection, recent_count, lookups, context,
                           coverage, chat_summary, initial_status, context_status,
                           recovery_trace, excluded_sources, model, routing_evidence,
                           adaptive_snapshot, token_usage, file_reference, target_ids):
    """Compose the public inspector from the request's actual inputs and outcomes."""
    public = build_agent_context(
        routing_trace, selection, recent_count, lookups,
    )
    checked_dates = context.get("activities", {}).get("checked_dates")
    if checked_dates:
        for source in public["context_sources"]:
            if source["source"] == "activities":
                source.update(selected=True, reason="Fresh calendar check for proposed dates: " + ", ".join(checked_dates))
    if coverage is not None:
        public["exam_coverage"] = coverage
        for source in public["context_sources"]:
            if source["source"] == "exams" and source["selected"]:
                source["reason"] += " " + coverage["notice"]
    if chat_summary:
        public['context_sources'].append({'source':'chat_summary','label':'Current-chat summary',
            'selected':True,'authority':'historical_summary','reason':'Bounded summary of older completed messages in this chat.'})
    public.update(initial_context_status=initial_status, context_status=context_status,
                  context_recovery=recovery_trace, excluded_sources=sorted(excluded_sources),
                  model=model,
                  adaptive_routing=build_adaptive_metadata(routing_evidence, adaptive_snapshot))
    public["token_usage"] = token_usage
    history = context.get('activities', {}).get('study_sessions')
    if history is not None:
        public['study_session_context'] = {
            'status': history.get('status', 'unavailable'), 'period': history.get('period'),
            'count': history.get('count', 0), 'recorded_count': history.get('recorded_count', 0),
            'automatic_missed_count': history.get('automatic_missed_count', 0),
            'actual_minutes': history.get('actual_minutes'),
            'truncated': bool(history.get('truncated')), 'period_limited': bool(history.get('period_limited')),
        }
    file_observation = context.get("files", {})
    # Keep only references and counts in persisted inspector metadata. Never
    # copy extracted text/chunks into recent/archive/durable conversation memory.
    public["file_context"] = {
        "status": context_status["files"],
        "detection": file_reference["method"] if file_reference else "context_selection",
        "chunk_count": file_observation.get("count", 0),
        "truncated": bool(file_observation.get("truncated")),
        "ambiguous": bool(file_observation.get("ambiguous")),
        "reference_matched": bool(file_reference and file_reference["method"] != "unknown_filename"
                                  and file_observation.get("files")),
        "requested_filenames": file_reference.get("filenames", []) if file_reference else [],
        "resolved_file_ids": (selection.get("files") or {}).get("file_ids", []),
        "files": [{key: item.get(key) for key in ("file_id", "filename", "file_type", "created_at", "chunk_count")}
                  for item in file_observation.get("files", [])],
    }
    public["file_refs"] = ([item["file_id"] for item in file_observation.get("files", [])][:3]
                           if context_status["files"] == "provided" else [])
    if target_ids:
        public['activity_target_lookup'] = {'requested_ids': target_ids,
            'matched_count': context.get('activities', {}).get('requested_activity_count', 0)}
    return public
