"""Stage 5: atomically replace summarized archive turns with one summary record."""

import hashlib
import json
import logging
import os
import stat
import tempfile
import uuid
from datetime import datetime, timezone

from backend.app import ai_memory
from backend.app.ai_archive_category_review import _category_rejection
from backend.app.ai_archive_summary import (
    ArchiveCategorySummary,
    BASE_ARCHIVE_CATEGORIES,
    _source_timestamp,
)


SUMMARY_RECORD_TYPE = "compressed_summary"
_logger = logging.getLogger(__name__)


class _PersistenceError(Exception):
    pass


def _failed(reason):
    return {"status": "failed", "reason": reason, "source_turns_removed": 0}


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _record_hash(record):
    return hashlib.sha256(_canonical_bytes(record)).hexdigest()


def _source_identity(record):
    turn_id = record.get("turn_id")
    if turn_id is not None:
        if not isinstance(turn_id, str):
            raise _PersistenceError("A source turn ID is invalid.")
        try:
            uuid.UUID(turn_id)
        except ValueError as exc:
            raise _PersistenceError("A source turn ID is invalid.") from exc
        return {"turn_id": turn_id, "record_sha256": _record_hash(record)}
    return {"turn_id": None, "record_sha256": _record_hash(record)}


def _validate_final_summary(final_result, classified_candidates):
    """Validate earlier-stage output and bind every ref to a compactable turn."""
    if not isinstance(classified_candidates, list):
        raise _PersistenceError("Final classified candidates must be a list.")
    if any(not isinstance(entry, dict) or entry.get("status") not in
           {"protected", "compactable"} for entry in classified_candidates):
        raise _PersistenceError("Every candidate needs a final protection status.")

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
    if not isinstance(summary, dict) or summary.get("success") is not True:
        raise _PersistenceError("A successful Stage 4 summary is required.")

    count = summary.get("source_turn_count")
    refs = summary.get("source_turn_refs")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 \
            or not isinstance(refs, list) or len(refs) != count:
        raise _PersistenceError("Source count and source refs do not agree.")
    compactable_indices = {
        index for index, entry in enumerate(classified_candidates)
        if entry["status"] == "compactable"
    }
    if count == 0:
        if compactable_indices:
            raise _PersistenceError("Compactable turns were omitted from the summary.")
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
        if entry["status"] != "compactable":
            raise _PersistenceError("A protected turn cannot be removed.")
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
        timestamp = ai_memory._archive_timestamp(record)
        if timestamp is not None:
            timestamps.append(timestamp)
    if seen_indices != compactable_indices:
        raise _PersistenceError("The summary does not cover every compactable candidate.")

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


def _read_archive_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _PersistenceError("The archive is not a regular file.")
        with os.fdopen(descriptor, "rb", closefd=False) as archive:
            return archive.read()
    finally:
        os.close(descriptor)


def _parse_lines(data):
    """Preserve original lines and reject malformed data before replacing anything."""
    lines = data.splitlines(keepends=True)
    records = []
    for line_index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _PersistenceError("The archive contains an invalid JSONL record.") from exc
        if not isinstance(record, dict) or ("turn" in record and not isinstance(record["turn"], dict)):
            raise _PersistenceError("The archive contains an invalid record.")
        records.append((line_index, record))
    return lines, records


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


def _append_record(data, record):
    separator = b"" if not data or data.endswith(b"\n") else b"\n"
    return data + separator + _canonical_bytes(record) + b"\n"


def _write_verified_temp(directory, data):
    descriptor, path = tempfile.mkstemp(prefix=".archive-stage5-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(data)
            output.flush()
            os.fsync(descriptor)
        if _read_archive_bytes(path) != data:
            raise _PersistenceError("A temporary archive write could not be verified.")
        return path
    except Exception:
        os.unlink(path)
        raise
    finally:
        os.close(descriptor)


def _fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _persist_locked(validated, classified_candidates):
    archive_path = ai_memory.ARCHIVE_FILE
    backup_path = archive_path.with_name(archive_path.stem + ".backup" + archive_path.suffix)
    directory = archive_path.parent
    temporary_paths = []
    replaced = False
    try:
        original_bytes = _read_archive_bytes(archive_path)
        lines, records = _parse_lines(original_bytes)
        existing_summaries = [record for _, record in records
                              if record.get("record_type") == SUMMARY_RECORD_TYPE]
        for record in existing_summaries:
            if record.get("source_fingerprint") == validated["source_fingerprint"]:
                raw_records = [item for _, item in records
                               if isinstance(item.get("turn"), dict)]
                if any(
                    item == classified_candidates[ref["source_index"]]["archived_turn"]
                    for ref in validated["source_turn_refs"] for item in raw_records
                ):
                    raise _PersistenceError("A saved summary still has raw source turns.")
                return {
                    "status": "already_persisted",
                    "summary_id": record.get("summary_id"),
                    "source_turns_removed": 0,
                    "raw_turns_remaining": sum("turn" in record for _, record in records),
                    "compressed_summary_count": len(existing_summaries),
                }

        selected_lines, raw_count = _match_raw_sources(
            records, classified_candidates, validated["source_turn_refs"]
        )
        summary_record = {
            "record_type": SUMMARY_RECORD_TYPE,
            "summary_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **validated,
        }
        # First fsync and read back a summary-bearing copy with ALL raw turns.
        prepared_bytes = _append_record(original_bytes, summary_record)
        prepared_path = _write_verified_temp(directory, prepared_bytes)
        temporary_paths.append(prepared_path)
        _, prepared_records = _parse_lines(_read_archive_bytes(prepared_path))
        if prepared_records[-1][1] != summary_record:
            raise _PersistenceError("The prepared summary could not be verified.")

        # Only after the summary is verified do we construct a deletion set.
        retained_bytes = b"".join(
            line for line_index, line in enumerate(lines) if line_index not in selected_lines
        )
        final_bytes = _append_record(retained_bytes, summary_record)
        final_path = _write_verified_temp(directory, final_bytes)
        temporary_paths.append(final_path)
        _, final_records = _parse_lines(_read_archive_bytes(final_path))
        if sum("turn" in record for _, record in final_records) != raw_count - len(selected_lines) \
                or final_records[-1][1] != summary_record:
            raise _PersistenceError("The final archive state could not be verified.")

        backup_temp = _write_verified_temp(directory, original_bytes)
        temporary_paths.append(backup_temp)
        os.replace(backup_temp, backup_path)
        _fsync_directory(directory)
        if _read_archive_bytes(backup_path) != original_bytes:
            raise _PersistenceError("The archive backup could not be verified.")

        os.replace(final_path, archive_path)
        replaced = True
        _fsync_directory(directory)
        if _read_archive_bytes(archive_path) != final_bytes:
            raise _PersistenceError("The final archive write could not be verified.")
        result = {
            "status": "success",
            "summary_id": summary_record["summary_id"],
            "source_turns_removed": len(selected_lines),
            "raw_turns_remaining": raw_count - len(selected_lines),
            "compressed_summary_count": len(existing_summaries) + 1,
        }
        _logger.info(
            "Stage 5 archive compaction complete: summary_id=%s, removed=%d, remaining=%d",
            result["summary_id"], result["source_turns_removed"],
            result["raw_turns_remaining"],
        )
        return result
    except Exception:
        if replaced:
            try:
                recovery_temp = _write_verified_temp(directory, original_bytes)
                temporary_paths.append(recovery_temp)
                os.replace(recovery_temp, archive_path)
                _fsync_directory(directory)
                if _read_archive_bytes(archive_path) != original_bytes:
                    raise _PersistenceError("Restored archive verification failed.")
            except Exception:
                return _failed("Archive verification failed; recover the original from the backup file.")
        return _failed("Archive persistence failed; original raw turns were preserved.")
    finally:
        for path in temporary_paths:
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    # Cleanup cannot turn a verified successful replace into a failure.
                    _logger.warning("Could not remove a Stage 5 temporary archive file.")


def persist_compacted_archive(final_result, classified_candidates):
    """Persist a verified Stage 4/4.5 summary without reclassifying any turn."""
    try:
        validated = _validate_final_summary(final_result, classified_candidates)
    except (ValueError, TypeError, _PersistenceError):
        return _failed("The summary or source-turn validation failed; archive unchanged.")
    if validated is None:
        return {"status": "nothing_to_persist"}
    try:
        with ai_memory._archive_write_lock():
            return _persist_locked(validated, classified_candidates)
    except Exception:
        return _failed("Archive persistence failed; original raw turns were preserved.")
