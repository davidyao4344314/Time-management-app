"""Pure planning tests with synthetic records; no live archive/model access."""

import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.app.infrastructure import atomic_files
from backend.app.ai.memory import compaction_plan as plan
from backend.app.ai.memory.records import canonical_bytes, parse_archive_lines
from backend.tests.ai.memory.test_ai_archive_persistence import _records, _classified_and_summary


class CompactionPlanTests(unittest.TestCase):
    def test_plan_removes_only_validated_sources_and_preserves_inputs(self):
        rows = _records(4)
        entries, summary = _classified_and_summary(rows, protected_indices={1}, summarized_indices={0, 3})
        snapshot = deepcopy((rows, entries, summary))
        validated = plan._validate_final_summary(summary, entries)
        stored = {"record_type": plan.SUMMARY_RECORD_TYPE, "summary_id": "synthetic-summary",
                  "created_at": "2026-10-01T00:00:00+00:00", **validated}
        original = b"".join(canonical_bytes(row) + b"\n" for row in rows)
        prepared = plan.prepare_compaction(original, entries, validated, stored)
        self.assertEqual(prepared["selected_lines"], {0, 3})
        final = [row for _, row in parse_archive_lines(prepared["final_bytes"])[1]]
        self.assertEqual(final, [rows[1], rows[2], stored])
        self.assertEqual((rows, entries, summary), snapshot)

    def test_preview_cannot_read_or_write_storage(self):
        rows = _records(3)
        entries, summary = _classified_and_summary(rows, protected_indices={1})
        with patch.object(atomic_files, "read_regular_bytes", side_effect=AssertionError("file read")), \
                patch.object(atomic_files, "write_verified_temp", side_effect=AssertionError("file write")):
            result = plan.preview_compacted_archive(
                summary, entries, rows, summary_id="synthetic-summary",
                created_at="2026-10-01T00:00:00+00:00",
            )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["would_remove"], [rows[0]["turn_id"], rows[2]["turn_id"]])
        self.assertEqual(result["raw_remaining"], [rows[1]["turn_id"]])


if __name__ == "__main__":
    unittest.main()
