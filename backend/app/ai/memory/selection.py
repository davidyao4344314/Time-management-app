"""Count-based compaction diagnostics and oldest-turn candidate selection."""

import logging
from datetime import datetime, timezone

from backend.app.ai.memory import archive_store, settings
from backend.app.ai.memory.records import archive_timestamp as _archive_timestamp

_logger = logging.getLogger("backend.app.ai_memory")


def archive_needs_compaction(archive_turn_count):
    """Report whether the archived-turn count exceeds the configured threshold."""
    return archive_turn_count > settings.ARCHIVE_TURN_THRESHOLD


def select_archive_compaction_candidates(*, batch_size=None):
    """Select the oldest archived turns; do not change archive or recent memory."""
    if batch_size is None:
        batch_size = settings.ARCHIVE_COMPACT_BATCH
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 0:
        raise ValueError("batch_size must be a non-negative integer.")

    entries = [
        (position, record, _archive_timestamp(record))
        for position, record in archive_store.iter_archived_turns()
    ]
    archive_turn_count = len(entries)
    needs_compaction = archive_needs_compaction(archive_turn_count)
    candidates = []
    if needs_compaction and batch_size:
        # Undated legacy turns have no reliable completion time. Keep their
        # original file order after the timestamped records rather than
        # inventing dates or treating append order as a timestamp.
        ordered = sorted(
            entries,
            key=lambda entry: (
                entry[2] is None,
                entry[2] or datetime.max.replace(tzinfo=timezone.utc),
                entry[0],
            ),
        )
        # Process the oldest identified session as one batch. Other sessions
        # remain untouched for subsequent passes; never blend their summaries.
        identified = [entry for entry in ordered
                      if isinstance(entry[1].get("session_id"), str) and entry[1]["session_id"]]
        if identified:
            session_id = identified[0][1]["session_id"]
            candidates = [entry for entry in identified
                          if entry[1]["session_id"] == session_id][:batch_size]

    known_times = [timestamp for _, _, timestamp in candidates if timestamp is not None]
    return {
        "needs_compaction": needs_compaction,
        "archive_turn_count": archive_turn_count,
        "candidate_count": len(candidates),
        "remaining_turn_count": archive_turn_count - len(candidates),
        "compaction_candidates": [record for _, record, _ in candidates],
        "oldest_candidate_timestamp": min(known_times).isoformat() if known_times else None,
        "newest_candidate_timestamp": max(known_times).isoformat() if known_times else None,
    }


def report_archive_size():
    """Report a threshold crossing without making a successful append fail."""
    # This diagnostic must not fail a completed archive append: callers remove
    # the recent turn only after _archive_turn returns.
    try:
        archive_turn_count = archive_store.get_archive_turn_count()
    except (OSError, UnicodeError):
        _logger.warning("Could not check the archive compaction threshold.")
    else:
        if archive_needs_compaction(archive_turn_count):
            _logger.warning(
                "Archive compaction required: %d archived turns.",
                archive_turn_count,
            )
