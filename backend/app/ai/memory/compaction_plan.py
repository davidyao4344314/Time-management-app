"""Pure source validation and compaction plans; no filesystem or model access."""

import hashlib

from backend.app.infrastructure.errors import MemoryUtilityError as _PersistenceError
from backend.app.ai.memory.category_policy import _category_rejection
from backend.app.ai.memory.contracts import ArchiveCategorySummary, BASE_ARCHIVE_CATEGORIES
from backend.app.ai.memory.records import (
    append_archive_record as _append_record, archive_timestamp as _archive_timestamp,
    canonical_bytes as _canonical_bytes, parse_archive_lines as _parse_lines,
    source_identity as _source_identity, source_timestamp as _source_timestamp,
)

SUMMARY_RECORD_TYPE = "compressed_summary"


def _validate_final_summary(final_result, classified_candidates):
    """Validate earlier-stage output and bind every ref to a compactable turn."""
    if final_result is None:
        return None
    if not isinstance(classified_candidates, list):
        raise _PersistenceError("Final classified candidates must be a list.")

    review_status = None
    added_category = None
    if isinstance(final_result, dict) and "summary" in final_result:
        review_status = final_result.get("status")
        if review_status not in {"accepted", "rejected", "not_needed"}:
            raise _PersistenceError("The Stage 4.5 result is invalid.")
        added_category = final_result.get("category_added")
        summary = final_result["summary"]
    else:
        summary = final_result
    if summary is None:
        return None
    if not isinstance(summary, dict) or summary.get("success") is not True:
        raise _PersistenceError("A successful Stage 4 summary is required.")

    count = summary.get("source_turn_count")
    refs = summary.get("source_turn_refs")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 \
            or not isinstance(refs, list) or len(refs) != count:
        raise _PersistenceError("Source count and source refs do not agree.")
    if count == 0:
        return None

    categories = summary.get("categories")
    if not isinstance(categories, dict):
        raise _PersistenceError("Summary categories are invalid.")
    category_names = set(categories)
    base_names = set(BASE_ARCHIVE_CATEGORIES)
    dynamic = category_names - base_names
    if not base_names <= category_names or len(dynamic) > 1:
        raise _PersistenceError("Summary categories are missing or excessive.")
    if review_status == "accepted":
        if len(dynamic) != 1 or added_category not in dynamic \
                or _category_rejection(added_category, base_names):
            raise _PersistenceError("The accepted dynamic category is invalid.")
        reviewed_refs = final_result.get("reclassified_item_refs")
        if not isinstance(reviewed_refs, list) or len(reviewed_refs) < 2 \
                or any(isinstance(ref, bool) or not isinstance(ref, int)
                       for ref in reviewed_refs):
            raise _PersistenceError("Dynamic-category evidence is invalid.")
        if summary.get("needs_category_review") is not False \
                or summary.get("uncategorized_item_refs") != []:
            raise _PersistenceError("Accepted category review is incomplete.")
    elif dynamic or added_category is not None:
        raise _PersistenceError("Only an accepted Stage 4.5 result may add a category.")
    if review_status is None and summary.get("needs_category_review") is not False:
        raise _PersistenceError("Stage 4.5 review has not completed.")

    validated_categories = {}
    try:
        for name, value in categories.items():
            validated_categories[name] = ArchiveCategorySummary.model_validate(value).model_dump()
    except ValueError as exc:
        raise _PersistenceError("A summary category is invalid.") from exc
    if not any(value["summary"] for value in validated_categories.values()):
        raise _PersistenceError("A nonempty summary is required before removing turns.")
    if dynamic and len(validated_categories[added_category]["summary"]) < 2:
        raise _PersistenceError("The dynamic category has insufficient summary evidence.")

    resolved_refs = []
    seen_indices = set()
    timestamps = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise _PersistenceError("A source ref is invalid.")
        index = ref.get("source_index")
        if isinstance(index, bool) or not isinstance(index, int) \
                or index < 0 or index >= len(classified_candidates) \
                or index in seen_indices:
            raise _PersistenceError("Source refs must identify unique candidates.")
        seen_indices.add(index)
        entry = classified_candidates[index]
        if not isinstance(entry, dict) or entry.get("status") != "compactable":
            if isinstance(entry, dict) and entry.get("status") == "protected":
                raise _PersistenceError("A protected turn cannot be removed.")
            raise _PersistenceError("A source turn has no final compactable classification.")
        record = entry.get("archived_turn")
        if not isinstance(record, dict) or not isinstance(record.get("turn"), dict):
            raise _PersistenceError("A compactable source record is invalid.")
        expected = {
            "source_index": index,
            "candidate_index": entry.get("candidate_index"),
            "session_id": record.get("session_id"),
            "timestamp": _source_timestamp(record),
        }
        if ref != expected:
            raise _PersistenceError("A source ref does not match its classified turn.")
        identity = _source_identity(record)
        resolved_refs.append({**expected, **identity})
        timestamp = _archive_timestamp(record)
        if timestamp is not None:
            timestamps.append(timestamp)
    source_records = [classified_candidates[ref["source_index"]]["archived_turn"]
                      for ref in resolved_refs]
    source_ids = {record["turn_id"] for record in source_records if record.get("turn_id")}
    for entry in classified_candidates:
        if not isinstance(entry, dict) or not isinstance(entry.get("archived_turn"), dict):
            continue
        record = entry["archived_turn"]
        turn_id = record.get("turn_id")
        same_source = (isinstance(turn_id, str) and turn_id in source_ids) or any(
            record == source for source in source_records
        )
        if same_source and entry.get("status") != "compactable":
            raise _PersistenceError("A source turn has conflicting protection classifications.")
    period_start = min(timestamps).isoformat() if timestamps else None
    period_end = max(timestamps).isoformat() if timestamps else None
    if summary.get("period_start") != period_start or summary.get("period_end") != period_end:
        raise _PersistenceError("Summary time range does not match its sources.")

    identity_tokens = sorted(
        (ref["turn_id"] or "legacy") + ":" + ref["record_sha256"]
        for ref in resolved_refs
    )
    source_fingerprint = hashlib.sha256(_canonical_bytes(identity_tokens)).hexdigest()
    return {
        "categories": validated_categories,
        "period_start": period_start,
        "period_end": period_end,
        "source_turn_count": count,
        "source_turn_refs": resolved_refs,
        "source_fingerprint": source_fingerprint,
    }


def _match_raw_sources(records, classified_candidates, source_refs):
    raw = [(line_index, record) for line_index, record in records
           if isinstance(record.get("turn"), dict)]
    selected = set()
    for ref in source_refs:
        candidate = classified_candidates[ref["source_index"]]["archived_turn"]
        if ref["turn_id"] is not None:
            matches = [(line_index, record) for line_index, record in raw
                       if record.get("turn_id") == ref["turn_id"]]
        else:
            matches = [(line_index, record) for line_index, record in raw
                       if "turn_id" not in record and record == candidate]
        if len(matches) != 1 or matches[0][1] != candidate \
                or matches[0][0] in selected:
            raise _PersistenceError("A source turn is missing or does not match uniquely.")
        selected.add(matches[0][0])
    return selected, len(raw)


def _verify_final_state(original_records, selected_lines, final_records, summary_record):
    """Check every retained record and its order, not just aggregate counts."""
    if len(selected_lines) != summary_record["source_turn_count"]:
        raise _PersistenceError("Removed count does not match the summary source count.")
    expected = [record for index, record in original_records if index not in selected_lines]
    expected.append(summary_record)
    actual = [record for _, record in final_records]
    if actual != expected:
        raise _PersistenceError("Non-source archive records or their order changed.")
    matching_summaries = sum(
        record.get("record_type") == SUMMARY_RECORD_TYPE
        and record.get("summary_id") == summary_record["summary_id"]
        for record in actual
    )
    if matching_summaries != 1:
        raise _PersistenceError("The new summary must appear exactly once.")


def prepare_compaction(original_bytes, classified_candidates, validated, summary_record):
    """Calculate and validate the exact archive bytes; never access storage."""
    lines, records = _parse_lines(original_bytes)
    selected_lines, raw_count = _match_raw_sources(
        records, classified_candidates, validated["source_turn_refs"]
    )
    # Prepare and validate the complete desired state before writing it.
    prepared_bytes = _append_record(original_bytes, summary_record)
    retained_bytes = b"".join(
        line for line_index, line in enumerate(lines) if line_index not in selected_lines
    )
    final_bytes = _append_record(retained_bytes, summary_record)
    _, final_records = _parse_lines(final_bytes)
    _verify_final_state(records, selected_lines, final_records, summary_record)
    return {
        "selected_lines": selected_lines, "raw_count": raw_count,
        "summary_record": summary_record, "prepared_bytes": prepared_bytes,
        "final_bytes": final_bytes,
    }


def preview_compacted_archive(final, entries, records, *, summary_id, created_at):
    """Use production validators/matching/verification, with no persistence."""
    try:
        validated = _validate_final_summary(final, entries)
        if validated is None:
            return {"status": "nothing_to_persist", "would_remove": []}
        indexed = list(enumerate(records))
        selected, _ = _match_raw_sources(indexed, entries, validated["source_turn_refs"])
        stored = {"record_type": SUMMARY_RECORD_TYPE,
                  "summary_id": summary_id,
                  "created_at": created_at, **validated}
        retained = [record for index, record in indexed if index not in selected]
        simulated = list(enumerate(retained + [stored]))
        _verify_final_state(indexed, selected, simulated, stored)
        return {"status": "dry_run", "summary_would_store": stored,
                "would_remove": [records[index]["turn_id"] for index in sorted(selected)],
                "raw_remaining": [record["turn_id"] for record in retained]}
    except Exception:
        return {"status": "failed", "reason": "Production Stage 5 validation rejected this result.",
                "would_remove": []}
