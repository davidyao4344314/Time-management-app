"""Durable-memory persistence and conservative deduplication; no model calls."""

import json
import os
import unicodedata
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

from backend.app.infrastructure.atomic_files import (
    exclusive_file_lock,
    fsync_directory as _fsync_directory,
    read_regular_bytes as _read_archive_bytes,
    write_verified_temp as _write_verified_temp,
)
from backend.app.ai.memory.paths import DURABLE_MEMORY_FILE
from backend.app.ai.memory.contracts import DurableMemoryStore
from backend.app.ai.memory.records import (
    canonical_bytes as _canonical_bytes,
    first_source_timestamp as _first_timestamp,
)


class _StorageError(RuntimeError):
    """Fixed safe messages only; underlying exceptions never reach the caller."""


def read_durable_memories(*, session_id):
    """Read one session's validated durable records; never initialize a store."""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("A session ID is required.")
    return read_authorized_durable_memories([session_id])


def read_authorized_durable_memories(session_ids):
    """Read and validate one snapshot for all authorized chats."""
    allowed = set(session_ids)
    if not allowed:
        return []
    if not all(isinstance(identity, str) and identity for identity in allowed):
        raise ValueError('A session ID is required.')
    try:
        data = _read_archive_bytes(DURABLE_MEMORY_FILE)
    except FileNotFoundError:
        return []
    store = DurableMemoryStore.model_validate(json.loads(data))
    return [memory.model_dump() for memory in store.durable_memories
            if memory.source_turn_refs[0].session_id in allowed]


def _normalized_content(content):
    """Conservative comparison: preserve word order, negations and numbers."""
    text = unicodedata.normalize("NFKC", content).casefold()
    text = " ".join(text.split()).rstrip(".!?").strip()
    # Keep internal punctuation: 1.5 hours and 1/5 hours are different facts.
    # This narrow active/passive pair has the same approval meaning. Do not use
    # an unordered bag of words: reversing 'before' relationships changes rules.
    if text in {
        "agent actions require user approval before execution",
        "user approval is required before executing agent actions",
    }:
        return "agent actions require user approval before execution"
    return text


def _memory_key(memory):
    return (memory["type"], memory["source_turn_refs"][0]["session_id"],
            _normalized_content(memory["content"]))


def _merge_memories(store, extracted):
    """Preserve existing IDs/content and append new provenance for duplicates."""
    state = deepcopy(store)
    active = {_memory_key(memory): memory for memory in state["durable_memories"]}
    created = reused = 0
    for memory in extracted:
        key = _memory_key(memory)
        if key in active:
            existing = active[key]
            known = {(ref["turn_id"], ref["record_sha256"])
                     for ref in existing["source_turn_refs"]}
            for ref in memory["source_turn_refs"]:
                identity = (ref["turn_id"], ref["record_sha256"])
                if identity not in known:
                    existing["source_turn_refs"].append(deepcopy(ref))
                    known.add(identity)
            existing["source_timestamp"] = _first_timestamp(existing["source_turn_refs"])
            reused += 1
        else:
            saved = {
                **deepcopy(memory), "memory_id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            state["durable_memories"].append(saved)
            active[key] = saved
            created += 1
    return DurableMemoryStore.model_validate(state).model_dump(), created, reused


@contextmanager
def _durable_write_lock():
    """Use the shared lock, preserving the durable store's regular-file check."""
    with exclusive_file_lock(
        DURABLE_MEMORY_FILE, require_regular_file=True,
        regular_file_error="The durable-memory lock must be a regular file.",
    ):
        yield


def _persist_memories(extracted):
    """Use shared verified-file utilities on the separate durable-memory file."""
    path = DURABLE_MEMORY_FILE
    backup = path.with_name(path.stem + ".backup" + path.suffix)
    temporary_paths = []
    replaced = False
    original = None
    try:
        try:
            original = _read_archive_bytes(path)
        except FileNotFoundError:
            pass
        store = {"durable_memories": []} if original is None else json.loads(original)
        store = DurableMemoryStore.model_validate(store).model_dump()
        new_state, created, reused = _merge_memories(store, extracted)
        if new_state == store:
            return created, reused
        final = _canonical_bytes(new_state) + b"\n"
        prepared = _write_verified_temp(path.parent, final)
        temporary_paths.append(prepared)
        if DurableMemoryStore.model_validate(json.loads(_read_archive_bytes(prepared))).model_dump() != new_state:
            raise ValueError("The prepared memory store could not be verified.")
        if original is not None:
            saved_backup = _write_verified_temp(path.parent, original)
            temporary_paths.append(saved_backup)
            os.replace(saved_backup, backup)
            _fsync_directory(path.parent)
            if _read_archive_bytes(backup) != original:
                raise ValueError("The durable-memory backup could not be verified.")
        os.replace(prepared, path)
        replaced = True
        _fsync_directory(path.parent)
        if _read_archive_bytes(path) != final:
            raise ValueError("The replaced memory store could not be verified.")
        return created, reused
    except Exception:
        if replaced:
            try:
                if original is None:
                    path.unlink()  # Remove only this failed first-time creation.
                else:
                    os.replace(backup, path)
                _fsync_directory(path.parent)
                if original is not None and _read_archive_bytes(path) != original:
                    raise OSError("Recovery verification failed.")
            except Exception:
                raise _StorageError("Durable-memory recovery needs attention; keep the backup file.") from None
        raise _StorageError("Durable-memory storage failed; existing memory was preserved.") from None
    finally:
        for temporary in temporary_paths:
            try:
                os.unlink(temporary)
            except OSError:
                pass
