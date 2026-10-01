"""Stage 5 uses temporary archives only; no live user archive is changed."""

import json
import tempfile
import unittest
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import ai_archive_persistence as persistence, ai_memory
from backend.app.ai_archive_summary import BASE_ARCHIVE_CATEGORIES


def _records(count=50, *, with_ids=True):
    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        record = {
            "session_id": "test-session",
            "timestamp": (first + timedelta(hours=index)).isoformat(),
            "turn": {"user": f"Turn {index + 1}", "assistant": "Reply"},
        }
        if with_ids:
            record["turn_id"] = str(uuid.uuid4())
        rows.append(record)
    return rows


def _classified_and_summary(rows, *, protected_indices=(), summarized_indices=None):
    protected = set(protected_indices)
    entries = [
        {"status": "protected" if index in protected else "compactable",
         "candidate_index": index, "archived_turn": deepcopy(record)}
        for index, record in enumerate(rows)
    ]
    compactable = [index for index in range(len(rows)) if index not in protected]
    if summarized_indices is not None:
        compactable = sorted(summarized_indices)
    categories = {
        name: {"summary": [], "keywords": []} for name in BASE_ARCHIVE_CATEGORIES
    }
    if compactable:
        categories["activities"] = {
            "summary": ["Discussed scheduled activities."],
            "keywords": ["activities"],
        }
    refs = [
        {"source_index": index, "candidate_index": index,
         "session_id": rows[index]["session_id"],
         "timestamp": rows[index]["timestamp"]}
        for index in compactable
    ]
    start = rows[compactable[0]]["timestamp"] if compactable else None
    end = rows[compactable[-1]]["timestamp"] if compactable else None
    summary = {
        "success": True,
        "period_start": start,
        "period_end": end,
        "source_turn_count": len(compactable),
        "source_turn_refs": refs,
        "categories": categories,
        "needs_category_review": False,
        "uncategorized_item_refs": [],
    }
    return entries, summary


class ArchivePersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.archive = Path(directory.name) / "archive.jsonl"
        archive_patch = patch.object(ai_memory, "ARCHIVE_FILE", self.archive)
        archive_patch.start()
        self.addCleanup(archive_patch.stop)

    def save_rows(self, rows):
        self.archive.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def read_rows(self):
        return [json.loads(line) for line in self.archive.read_text().splitlines()]

    def test_a_only_forty_compactable_turns_are_removed(self):
        rows = _records()
        protected_indices = {index for index in range(0, 50, 5)}
        entries, summary = _classified_and_summary(rows, protected_indices=protected_indices)
        self.save_rows(rows)
        before = self.archive.read_bytes()

        result = persistence.persist_compacted_archive(summary, entries)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_turns_removed"], 40)
        self.assertEqual(result["raw_turns_remaining"], 10)
        self.assertEqual(result["compressed_summary_count"], 1)
        remaining = self.read_rows()
        self.assertEqual(remaining[:10], [rows[index] for index in sorted(protected_indices)])
        saved = remaining[-1]
        self.assertEqual(saved["record_type"], "compressed_summary")
        self.assertEqual(saved["summary_id"], result["summary_id"])
        self.assertEqual(saved["source_turn_count"], 40)
        self.assertEqual(len(saved["source_turn_refs"]), 40)
        self.assertEqual(saved["period_start"], summary["period_start"])
        self.assertEqual(saved["period_end"], summary["period_end"])
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        backup = self.archive.with_name("archive.backup.jsonl")
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ai_memory.get_archive_turn_count(), 10)

    def test_newer_unselected_turns_keep_their_order(self):
        rows = _records(55)
        entries, summary = _classified_and_summary(rows[:50],
                                                    protected_indices={0, 9, 19})
        self.save_rows(rows)
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "success")
        expected = [rows[index] for index in (0, 9, 19)] + rows[50:]
        self.assertEqual(self.read_rows()[:-1], expected)

    def test_b_missing_source_aborts_without_mutation(self):
        rows = _records(3)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows[:2])
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["source_turns_removed"], 0)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_c_protected_source_ref_aborts(self):
        rows = _records(3)
        entries, summary = _classified_and_summary(rows, protected_indices={1})
        summary["source_turn_refs"][1] = {
            "source_index": 1, "candidate_index": 1,
            "session_id": rows[1]["session_id"], "timestamp": rows[1]["timestamp"],
        }
        self.save_rows(rows)
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)

    def test_d_invalid_summary_aborts(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        for invalid in (
            {**summary, "source_turn_count": 3},
            {**summary, "categories": {
                name: {"summary": [], "keywords": []} for name in BASE_ARCHIVE_CATEGORIES
            }},
            {**summary, "categories": {"general": {"summary": ["Lost"], "keywords": []}}},
            {**summary, "period_end": "2020-01-01T00:00:00+00:00"},
        ):
            with self.subTest(invalid=invalid):
                result = persistence.persist_compacted_archive(invalid, entries)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.archive.read_bytes(), before)

    def test_e_temp_write_failure_preserves_original(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        with patch.object(persistence, "_write_verified_temp", side_effect=OSError("disk full")):
            result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)

    def test_failure_after_replace_restores_original_from_backup(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        calls = 0
        real_fsync = persistence._fsync_directory

        def fail_after_replace(directory):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("verification failed after replacement")
            return real_fsync(directory)

        with patch.object(persistence, "_fsync_directory", side_effect=fail_after_replace):
            result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(self.archive.with_name("archive.backup.jsonl").read_bytes(), before)

    def test_f_retry_does_not_duplicate_summary_or_delete_again(self):
        rows = _records(3)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        first = persistence.persist_compacted_archive(summary, entries)
        after_first = self.archive.read_bytes()
        second = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "already_persisted")
        self.assertEqual(second["summary_id"], first["summary_id"])
        self.assertEqual(second["source_turns_removed"], 0)
        self.assertEqual(self.archive.read_bytes(), after_first)
        self.assertEqual(len(self.read_rows()), 1)

    def test_retry_with_reintroduced_raw_source_reports_inconsistency(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        self.assertEqual(persistence.persist_compacted_archive(summary, entries)["status"],
                         "success")
        with self.archive.open("a", encoding="utf-8") as archive:
            archive.write(json.dumps(rows[0]) + "\n")
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)

    def test_g_no_compactable_turns_does_not_touch_archive(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows, protected_indices={0, 1})
        self.save_rows(rows)
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result, {"status": "nothing_to_persist"})
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertFalse(self.archive.with_name("archive.backup.jsonl").exists())

    def test_h_mixed_batch_removes_only_summary_sources(self):
        rows = _records(6)
        entries, summary = _classified_and_summary(
            rows, protected_indices={0, 4}, summarized_indices={1, 5},
        )
        entries[3]["status"] = "uncertain"  # Not included in Stage 4.
        original_entries, original_summary = deepcopy(entries), deepcopy(summary)
        self.save_rows(rows)
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_turns_removed"], 2)
        self.assertEqual(result["raw_turns_remaining"], 4)
        self.assertEqual(self.read_rows()[:-1], [rows[index] for index in (0, 2, 3, 4)])
        self.assertEqual(entries, original_entries)
        self.assertEqual(summary, original_summary)

    def test_unknown_classification_on_a_source_aborts(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        entries[1]["status"] = "uncertain"
        self.save_rows(rows)
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertIn("classification", result["reason"])
        self.assertEqual(self.archive.read_bytes(), before)

    def test_conflicting_classifications_of_the_same_source_abort(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        entries.append({"status": "protected", "archived_turn": deepcopy(rows[0])})
        self.save_rows(rows)
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertIn("conflicting protection", result["reason"])
        self.assertEqual(self.archive.read_bytes(), before)

    def test_missing_summary_or_zero_sources_does_not_touch_archive(self):
        rows = _records(2)
        entries, empty_summary = _classified_and_summary(rows, summarized_indices=set())
        self.save_rows(rows)
        before = self.archive.read_bytes()
        for result_input in (None, empty_summary):
            with self.subTest(result_input=result_input):
                result = persistence.persist_compacted_archive(result_input, entries)
                self.assertEqual(result, {"status": "nothing_to_persist"})
                self.assertEqual(self.archive.read_bytes(), before)
        self.assertFalse(self.archive.with_name("archive.jsonl.lock").exists())

    def test_final_replace_failure_keeps_archive_and_backup(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        real_replace = persistence.os.replace

        def fail_final_replace(source, destination):
            if Path(destination) == self.archive:
                raise OSError("simulated replace failure")
            return real_replace(source, destination)

        with patch.object(persistence.os, "replace", side_effect=fail_final_replace):
            result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertIn("replacing the archive", result["reason"])
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(self.archive.with_name("archive.backup.jsonl").read_bytes(), before)

    def test_final_temp_or_backup_write_failure_preserves_original(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        real_write = persistence._write_verified_temp
        for failing_write in (2, 3):
            with self.subTest(failing_write=failing_write):
                self.save_rows(rows)
                before = self.archive.read_bytes()
                writes = 0

                def fail_write(directory, data):
                    nonlocal writes
                    writes += 1
                    if writes == failing_write:
                        raise OSError("simulated write failure")
                    return real_write(directory, data)

                with patch.object(persistence, "_write_verified_temp", side_effect=fail_write):
                    result = persistence.persist_compacted_archive(summary, entries)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.archive.read_bytes(), before)

    def test_summary_read_back_failure_preserves_original(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        real_read = persistence._read_archive_bytes

        def incorrect_temp_read(path):
            if Path(path).name.startswith(".archive-stage5-"):
                return b"incorrect bytes"
            return real_read(path)

        with patch.object(persistence, "_read_archive_bytes", side_effect=incorrect_temp_read):
            result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertIn("temporary archive write", result["reason"])
        self.assertEqual(self.archive.read_bytes(), before)

    def test_failed_automatic_recovery_keeps_original_in_backup(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        before = self.archive.read_bytes()
        real_write = persistence._write_verified_temp
        real_fsync = persistence._fsync_directory
        writes = 0
        syncs = 0

        def fail_recovery_write(directory, data):
            nonlocal writes
            writes += 1
            if writes == 4:
                raise OSError("simulated recovery failure")
            return real_write(directory, data)

        def fail_post_replace_sync(directory):
            nonlocal syncs
            syncs += 1
            if syncs == 2:
                raise OSError("simulated verification failure")
            return real_fsync(directory)

        with patch.object(persistence, "_write_verified_temp", side_effect=fail_recovery_write), \
                patch.object(persistence, "_fsync_directory", side_effect=fail_post_replace_sync):
            result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertIn("recover the original from the backup", result["reason"])
        self.assertEqual(self.archive.with_name("archive.backup.jsonl").read_bytes(), before)

    def test_retained_record_corruption_or_reordering_aborts_before_replace(self):
        rows = _records(4)
        entries, summary = _classified_and_summary(rows, summarized_indices={1, 3})
        real_write = persistence._write_verified_temp
        for damage in ("change", "reorder"):
            with self.subTest(damage=damage):
                self.save_rows(rows)
                before = self.archive.read_bytes()
                writes = 0

                def corrupt_second_temp(directory, data):
                    nonlocal writes
                    writes += 1
                    path = real_write(directory, data)
                    if writes == 2:
                        output = [json.loads(line) for line in data.splitlines()]
                        if damage == "change":
                            output[0]["turn"]["user"] = "corrupted"
                        else:
                            output[0], output[1] = output[1], output[0]
                        Path(path).write_text(
                            "".join(json.dumps(record) + "\n" for record in output),
                            encoding="utf-8",
                        )
                    return path

                with patch.object(persistence, "_write_verified_temp", side_effect=corrupt_second_temp):
                    result = persistence.persist_compacted_archive(summary, entries)
                self.assertEqual(result["status"], "failed")
                self.assertIn("Non-source archive records", result["reason"])
                self.assertEqual(self.archive.read_bytes(), before)

    def test_legacy_turns_need_an_exact_unique_match(self):
        rows = _records(2, with_ids=False)
        entries, summary = _classified_and_summary(rows)
        self.save_rows(rows)
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "success")
        self.assertTrue(all(ref["turn_id"] is None for ref in self.read_rows()[0]["source_turn_refs"]))

        rows = _records(1, with_ids=False)
        self.save_rows(rows + deepcopy(rows))
        entries, summary = _classified_and_summary(rows)
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)

    def test_malformed_archive_aborts_before_backup_or_replace(self):
        rows = _records(1)
        entries, summary = _classified_and_summary(rows)
        self.archive.write_text(json.dumps(rows[0]) + "\nnot JSON\n", encoding="utf-8")
        before = self.archive.read_bytes()
        result = persistence.persist_compacted_archive(summary, entries)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertFalse(self.archive.with_name("archive.backup.jsonl").exists())

    def test_new_archive_turns_have_stable_ids(self):
        with patch.object(ai_memory, "get_archive_turn_count", return_value=0):
            ai_memory._archive_turn("test-session", {
                "timestamp": "2026-09-01T00:00:00+00:00",
                "user": "Hello", "assistant": "Hi",
            })
        record = self.read_rows()[0]
        self.assertEqual(str(uuid.UUID(record["turn_id"])), record["turn_id"])
        self.assertTrue(self.archive.with_name("archive.jsonl.lock").exists())

    def test_stage_four_point_five_dynamic_category_is_persisted(self):
        rows = _records(2)
        entries, summary = _classified_and_summary(rows)
        summary["categories"]["career"] = {
            "summary": ["Discussed internships.", "Reviewed CV preparation."],
            "keywords": ["internships", "CV"],
        }
        envelope = {
            "status": "accepted", "category_added": "career",
            "reclassified_item_refs": [0, 1], "summary": summary,
        }
        self.save_rows(rows)
        result = persistence.persist_compacted_archive(envelope, entries)
        self.assertEqual(result["status"], "success")
        self.assertIn("career", self.read_rows()[-1]["categories"])


if __name__ == "__main__":
    unittest.main()
