"""Shared memory utilities tested offline with synthetic records/temporary files."""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from backend.app import ai_archive_persistence as persistence
from backend.app import ai_archive_summary as summary
from backend.app import ai_durable_memory as durable
from backend.app import ai_memory
from backend.app.infrastructure import atomic_files, privacy
from backend.app.infrastructure.errors import MemoryUtilityError
from backend.app.memory import paths, records


class MemoryUtilityTests(unittest.TestCase):
    def test_existing_helper_imports_remain_compatible(self):
        aliases = (
            (persistence._canonical_bytes, records.canonical_bytes),
            (persistence._record_hash, records.record_hash),
            (persistence._source_identity, records.source_identity),
            (persistence._parse_lines, records.parse_archive_lines),
            (persistence._append_record, records.append_archive_record),
            (persistence._read_archive_bytes, atomic_files.read_regular_bytes),
            (persistence._fsync_directory, atomic_files.fsync_directory),
            (persistence._PersistenceError, MemoryUtilityError),
            (summary._source_timestamp, records.source_timestamp),
            (summary._archive_timestamp, records.archive_timestamp),
            (ai_memory._archive_timestamp, records.archive_timestamp),
            (ai_memory._redact_secrets, privacy.redact_secrets),
            (durable._canonical_bytes, records.canonical_bytes),
            (durable._source_identity, records.source_identity),
            (durable._source_timestamp, records.source_timestamp),
            (durable._first_timestamp, records.first_source_timestamp),
            (durable._redact_secrets, privacy.redact_secrets),
            (durable._read_archive_bytes, atomic_files.read_regular_bytes),
            (durable._write_verified_temp, atomic_files.write_verified_temp),
        )
        for original, shared in aliases:
            with self.subTest(name=shared.__name__):
                self.assertIs(original, shared)

    def test_original_storage_locations_are_preserved(self):
        backend_directory = Path(__file__).resolve().parent
        self.assertEqual(paths.BACKEND_DIRECTORY, backend_directory)
        self.assertEqual(ai_memory.ARCHIVE_FILE, backend_directory / "ai_memory_archive.jsonl")
        self.assertEqual(durable.DURABLE_MEMORY_FILE, backend_directory / "ai_durable_memories.json")

    def test_canonical_bytes_and_fingerprints_preserve_identity(self):
        value = {"turn": {"user": "Study", "assistant": "Reply"}, "session_id": "example"}
        before = deepcopy(value)
        canonical = b'{"session_id":"example","turn":{"assistant":"Reply","user":"Study"}}'
        self.assertEqual(records.canonical_bytes(value), canonical)
        expected_hash = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(records.source_identity(value), {
            "turn_id": None, "record_sha256": expected_hash,
        })
        self.assertEqual(records.record_hash(dict(reversed(list(value.items())))), expected_hash)
        self.assertEqual(value, before)
        with_id = {**value, "turn_id": "00000000-0000-4000-8000-000000000001"}
        self.assertEqual(records.source_identity(with_id)["turn_id"], with_id["turn_id"])

    def test_invalid_source_ids_keep_the_safe_error(self):
        for value in (12, "not-a-uuid", ""):
            with self.subTest(value=value), self.assertRaisesRegex(
                MemoryUtilityError, "A source turn ID is invalid",
            ):
                records.source_identity({"turn_id": value})

    def test_timestamps_keep_legacy_values_without_inventing_dates(self):
        legacy = {"turn": {"timestamp": "2026-09-30T10:00:00+12:00"}}
        self.assertEqual(records.source_timestamp(legacy), "2026-09-30T10:00:00+12:00")
        self.assertEqual(records.archive_timestamp(legacy), datetime(2026, 9, 29, 22, tzinfo=timezone.utc))
        for value in (None, "invalid", "2026-09-30", "2026-09-30T10:00:00"):
            with self.subTest(value=value):
                self.assertIsNone(records.archive_timestamp({"timestamp": value, "turn": {}}))
        self.assertIsNone(records.source_timestamp({"turn": {}}))
        self.assertEqual(records.first_source_timestamp([
            {"timestamp": None}, {"timestamp": "existing timestamp"}, {"timestamp": "later timestamp"},
        ]), "existing timestamp")

    def test_archive_parsing_preserves_lines_and_record_positions(self):
        raw = b'\n{"turn":{"user":"Study","assistant":"Reply"}}\r\n\n{"record_type":"compressed_summary"}\n'
        lines, parsed = records.parse_archive_lines(raw)
        self.assertEqual(b"".join(lines), raw)
        self.assertEqual([position for position, _ in parsed], [1, 3])
        self.assertEqual(parsed[1][1], {"record_type": "compressed_summary"})
        self.assertEqual(records.append_archive_record(b'{"old":true}', {"new": True}),
                         b'{"old":true}\n{"new":true}\n')

    def test_malformed_archive_records_are_rejected(self):
        for raw in (b"invalid-json", b"[]\n", b'{"turn":null}\n', b"\xff\n"):
            with self.subTest(raw=raw), self.assertRaises(MemoryUtilityError):
                records.parse_archive_lines(raw)

    def test_redaction_is_recursive_and_does_not_mutate_the_input(self):
        fake_key = "sk-" + "synthetic" * 4
        configured_key = "configured-test-secret-without-prefix"
        value = {"user": fake_key, "assistant": [configured_key, "Normal reply"], "count": 2}
        before = deepcopy(value)
        with patch.dict(os.environ, {"OPENAI_API_KEY": configured_key}):
            redacted = privacy.redact_secrets(value)
        self.assertEqual(redacted, {
            "user": "[redacted API key]",
            "assistant": ["[redacted API key]", "Normal reply"], "count": 2,
        })
        self.assertEqual(value, before)

    def test_verified_temporary_file_has_original_prefix_permissions_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(atomic_files.write_verified_temp(directory, b"synthetic memory\n"))
            self.assertTrue(prepared.name.startswith(".archive-stage5-"))
            self.assertEqual(prepared.stat().st_mode & 0o777, 0o600)
            self.assertEqual(atomic_files.read_regular_bytes(prepared), b"synthetic memory\n")
            atomic_files.fsync_directory(directory)

    def test_failed_temporary_verification_cleans_up_without_changing_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "original.json"
            existing.write_bytes(b"original synthetic data")
            with self.assertRaisesRegex(MemoryUtilityError, "temporary archive write"):
                atomic_files.write_verified_temp(directory, b"new bytes", read_bytes=lambda path: b"wrong bytes")
            self.assertEqual(existing.read_bytes(), b"original synthetic data")
            self.assertEqual(list(Path(directory).iterdir()), [existing])

    def test_failed_temporary_write_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "original.json"
            existing.write_bytes(b"original synthetic data")
            with patch.object(atomic_files.os, "fsync", side_effect=OSError("simulated disk failure")), \
                    self.assertRaises(OSError):
                atomic_files.write_verified_temp(directory, b"new bytes")
            self.assertEqual(existing.read_bytes(), b"original synthetic data")
            self.assertEqual(list(Path(directory).iterdir()), [existing])

    def test_reader_rejects_symlinks_and_nonregular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.json"
            original.write_bytes(b"untouched")
            link = Path(directory) / "link.json"
            link.symlink_to(original)
            with self.assertRaises(OSError):
                atomic_files.read_regular_bytes(link)
            with self.assertRaises(MemoryUtilityError):
                atomic_files.read_regular_bytes(Path(directory))
            self.assertEqual(original.read_bytes(), b"untouched")

    def test_legacy_temp_writer_preserves_the_readback_failure_hook(self):
        with patch.object(persistence, "write_verified_temp", return_value="temporary-path") as writer:
            self.assertEqual(persistence._write_verified_temp("directory", b"bytes"), "temporary-path")
        writer.assert_called_once_with("directory", b"bytes", read_bytes=persistence._read_archive_bytes)

    def test_sidecar_lock_is_exclusive_and_survives_target_replacement(self):
        child_code = dedent("""
            import fcntl, os, sys
            descriptor = os.open(sys.argv[1], os.O_RDWR)
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    print("locked")
                else:
                    print("available")
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        """)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "synthetic.json"
            target.write_bytes(b"old")
            lock = target.with_name(target.name + ".lock")
            with atomic_files.exclusive_file_lock(target, require_regular_file=True):
                inode = lock.stat().st_ino
                prepared = atomic_files.write_verified_temp(directory, b"new")
                os.replace(prepared, target)
                result = subprocess.run([sys.executable, "-B", "-c", child_code, str(lock)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "locked")
                self.assertEqual(lock.stat().st_ino, inode)
                self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
            result = subprocess.run([sys.executable, "-B", "-c", child_code, str(lock)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "available")

    def test_lock_wrappers_preserve_path_overrides_and_regular_file_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.jsonl"
            store = Path(directory) / "durable.json"
            with patch.object(ai_memory, "ARCHIVE_FILE", archive), \
                    patch.object(ai_memory, "exclusive_file_lock") as lock:
                with ai_memory._archive_write_lock():
                    pass
                lock.assert_called_once_with(archive)
            with patch.object(durable, "DURABLE_MEMORY_FILE", store), \
                    patch.object(durable, "exclusive_file_lock") as lock:
                with durable._durable_write_lock():
                    pass
                lock.assert_called_once_with(
                    store, require_regular_file=True,
                    regular_file_error="The durable-memory lock must be a regular file.",
                )

    def test_lock_rejects_symlinks_and_keeps_optional_regular_file_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "synthetic.json"
            lock = target.with_name(target.name + ".lock")
            original = Path(directory) / "untouched.txt"
            original.write_bytes(b"untouched")
            lock.symlink_to(original)
            with self.assertRaises(OSError), atomic_files.exclusive_file_lock(target):
                pass
            self.assertEqual(original.read_bytes(), b"untouched")
            lock.unlink()
            with patch.object(atomic_files.stat, "S_ISREG", return_value=False):
                with self.assertRaisesRegex(ValueError, "custom lock error"), \
                        atomic_files.exclusive_file_lock(
                            target, require_regular_file=True, regular_file_error="custom lock error",
                        ):
                    pass
                with atomic_files.exclusive_file_lock(target):
                    pass

    def test_utilities_import_without_services_or_storage_side_effects(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            code = dedent(f"""
                import sys
                from pathlib import Path
                sys.path.insert(0, {str(root)!r})
                sys.modules["openai"] = None
                sys.modules["sqlite3"] = None
                from backend.app.infrastructure import atomic_files, privacy
                from backend.app.memory import paths, records
                for name in (
                    "backend.app.ai_memory", "backend.app.ai_archive_persistence",
                    "backend.app.ai_archive_summary", "backend.app.ai_durable_memory",
                    "backend.app.ai_config", "backend.app.ai_proposal",
                ):
                    assert name not in sys.modules, name
                assert not list(Path.cwd().iterdir())
                assert paths.BACKEND_DIRECTORY == Path({str(root / 'backend')!r})
            """)
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=directory,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_durable_memory_import_no_longer_depends_on_archive_stages(self):
        code = dedent("""
            import sys
            for name in (
                "backend.app.ai_memory", "backend.app.ai_archive_persistence",
                "backend.app.ai_archive_summary",
            ):
                sys.modules[name] = None
            from backend.app import ai_durable_memory
            assert ai_durable_memory._source_identity.__module__ == "backend.app.memory.records"
        """)
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
