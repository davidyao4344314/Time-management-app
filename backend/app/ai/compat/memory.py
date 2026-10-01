"""Compatibility facade for the separated recent/archive memory modules."""

from backend.app.infrastructure.module_compat import forward_module
from backend.app.ai.memory import archive_store, recent, selection, settings

forward_module(__name__, {
    "has_session": (recent, "has_session"),
    "get_recent_turns": (recent, "get_recent_turns"),
    "enforce_recent_limit": (recent, "enforce_recent_limit"),
    "add_completed_turn": (recent, "add_completed_turn"),
    "_archive_excess_turns": (recent, "_archive_excess_turns"),
    "_archive_turn": (recent, "_archive_turn"),
    "_sessions": (recent, "_sessions"),
    "_lock": (recent, "_lock"),
    "get_max_recent_turns": (recent, "get_max_recent_turns"),
    "datetime": (recent, "datetime"),
    "timezone": (recent, "timezone"),
    "deque": (recent, "deque"),
    "deepcopy": (recent, "deepcopy"),
    "Lock": (recent, "Lock"),
    "ARCHIVE_FILE": (archive_store, "ARCHIVE_FILE"),
    "exclusive_file_lock": (archive_store, "exclusive_file_lock"),
    "_redact_secrets": (archive_store, "_redact_secrets"),
    "_API_KEY_PATTERN": (archive_store, "_API_KEY_PATTERN"),
    "get_archive_turn_count": (archive_store, "get_archive_turn_count"),
    "fcntl": (archive_store, "fcntl"),
    "os": (archive_store, "os"),
    "json": (archive_store, "json"),
    "uuid": (archive_store, "uuid"),
    "contextmanager": (archive_store, "contextmanager"),
    "archive_needs_compaction": (selection, "archive_needs_compaction"),
    "select_archive_compaction_candidates": (selection, "select_archive_compaction_candidates"),
    "_archive_timestamp": (selection, "_archive_timestamp"),
    "_logger": (selection, "_logger"),
    "ARCHIVE_TURN_THRESHOLD": (settings, "ARCHIVE_TURN_THRESHOLD"),
    "ARCHIVE_COMPACT_BATCH": (settings, "ARCHIVE_COMPACT_BATCH"),
    "_archive_write_lock": (archive_store, "archive_write_lock"),
    "_iter_archived_turns": (archive_store, "iter_archived_turns"),
})
