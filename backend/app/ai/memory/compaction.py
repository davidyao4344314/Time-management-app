"""Stage 5: atomically replace summarized archive turns with one summary record."""

import logging
import os
import uuid
from datetime import datetime, timezone

from backend.app.ai.memory import archive_store as ai_memory
from backend.app.ai.memory.compaction_plan import (
    SUMMARY_RECORD_TYPE,
    _validate_final_summary, _match_raw_sources, _verify_final_state, prepare_compaction,
)
from backend.app.infrastructure.atomic_files import (
    fsync_directory as _fsync_directory,
    read_regular_bytes as _read_archive_bytes,
    write_verified_temp,
)
from backend.app.infrastructure.errors import MemoryUtilityError as _PersistenceError
from backend.app.ai.memory.records import (
    append_archive_record as _append_record,
    archive_timestamp as _archive_timestamp,
    canonical_bytes as _canonical_bytes,
    parse_archive_lines as _parse_lines,
    record_hash as _record_hash,
    source_identity as _source_identity,
    source_timestamp as _source_timestamp,
)
from backend.app.ai.memory.contracts import ArchiveCategorySummary, BASE_ARCHIVE_CATEGORIES


_logger = logging.getLogger("backend.app.ai_archive_persistence")


def _failed(reason):
    return {"status": "failed", "reason": reason, "source_turns_removed": 0}


def _write_verified_temp(directory, data):
    """Delegate while retaining the existing read-back failure-test hook."""
    return write_verified_temp(directory, data, read_bytes=_read_archive_bytes)


def _persist_locked(validated, classified_candidates):
    archive_path = ai_memory.ARCHIVE_FILE
    backup_path = archive_path.with_name(archive_path.stem + ".backup" + archive_path.suffix)
    directory = archive_path.parent
    temporary_paths = []
    replaced = False
    phase = "reading the archive"
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

        phase = "matching source turns"
        summary_record = {
            "record_type": SUMMARY_RECORD_TYPE,
            "summary_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **validated,
        }
        plan = prepare_compaction(original_bytes, classified_candidates, validated, summary_record)
        selected_lines, raw_count = plan["selected_lines"], plan["raw_count"]
        prepared_bytes, final_bytes = plan["prepared_bytes"], plan["final_bytes"]

        # First fsync and read back the summary copy with ALL raw turns retained.
        phase = "writing and verifying the summary"
        prepared_path = _write_verified_temp(directory, prepared_bytes)
        temporary_paths.append(prepared_path)
        _, prepared_records = _parse_lines(_read_archive_bytes(prepared_path))
        if [record for _, record in prepared_records] != [record for _, record in records] + [summary_record]:
            raise _PersistenceError("The prepared summary could not be verified.")

        phase = "writing and verifying the final temporary archive"
        final_path = _write_verified_temp(directory, final_bytes)
        temporary_paths.append(final_path)
        _, final_records = _parse_lines(_read_archive_bytes(final_path))
        _verify_final_state(records, selected_lines, final_records, summary_record)

        phase = "writing and verifying the backup"
        backup_temp = _write_verified_temp(directory, original_bytes)
        temporary_paths.append(backup_temp)
        os.replace(backup_temp, backup_path)
        _fsync_directory(directory)
        if _read_archive_bytes(backup_path) != original_bytes:
            raise _PersistenceError("The archive backup could not be verified.")

        phase = "replacing the archive"
        os.replace(final_path, archive_path)
        replaced = True
        phase = "verifying the replaced archive"
        _fsync_directory(directory)
        saved_bytes = _read_archive_bytes(archive_path)
        if saved_bytes != final_bytes:
            raise _PersistenceError("The final archive write could not be verified.")
        _, saved_records = _parse_lines(saved_bytes)
        _verify_final_state(records, selected_lines, saved_records, summary_record)
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
    except Exception as error:
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
        detail = str(error) if isinstance(error, _PersistenceError) else f"Failed while {phase}."
        return _failed(f"{detail} Original raw turns were preserved.")
    finally:
        for path in temporary_paths:
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    # Cleanup cannot turn a verified successful replace into a failure.
                    _logger.warning("Could not remove a Stage 5 temporary archive file.")


def persist_compacted_archive(final_result, classified_candidates):
    """Persist only a verified summary's sources; leave other candidates raw."""
    try:
        validated = _validate_final_summary(final_result, classified_candidates)
    except _PersistenceError as error:
        return _failed(f"{error} Archive unchanged.")
    except (ValueError, TypeError):
        return _failed("The summary or source-turn validation failed; archive unchanged.")
    if validated is None:
        return {"status": "nothing_to_persist"}
    try:
        with ai_memory.archive_write_lock():
            return _persist_locked(validated, classified_candidates)
    except Exception:
        return _failed("Archive persistence failed; original raw turns were preserved.")
