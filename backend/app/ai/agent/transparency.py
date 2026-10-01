"""Public request metadata, never model reasoning, prompts or session secrets."""

from backend.app.infrastructure.privacy import redact_secrets

SOURCE_INFO = {
    "activities": ("Activities", "current"),
    "exams": ("Exams", "current"),
    "recent_memory": ("Recent memory", "historical"),
    "raw_archive": ("Raw archive", "historical"),
    "compressed_archive": ("Compressed archive", "historical_summary"),
    "durable": ("Durable memory", "historical"),
}


def _text(value, limit):
    if not isinstance(value, str):
        return None
    cleaned = redact_secrets(value)
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def build_agent_context(routing, selection, recent_count, lookups):
    """Describe actual selection/retrieval; no inference from the user's words."""
    selected_memory = {source for lookup in lookups for source in lookup["sources"]}
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
        else:
            selected = source in selected_memory
            reason = "Requested for a bounded, session-scoped historical lookup."
        sources.append({"source": source, "label": label, "selected": selected,
                        "authority": authority,
                        "reason": reason if selected else "Not selected for this request."})

    retrieved, seen = [], {}
    lookup_details = []
    for lookup in lookups:
        result = lookup["result"]
        lookup_details.append({
            "phase": lookup["phase"], "sources": lookup["sources"],
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
