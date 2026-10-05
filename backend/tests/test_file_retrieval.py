"""Read-only file context, isolation, deterministic matching and hard limits."""

import json
import sqlite3
import unittest

from pydantic import ValidationError
from backend.app.files import storage
from backend.app.files.contracts import FileSelection, MAX_CONTEXT_CHUNKS, MAX_CONTEXT_CHARS
from backend.app.files.ingestion import ingest_file
from backend.app.files.retrieval import detect_file_reference, retrieve_file_context


class FileRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        storage.migrate(self.connection)
        self.file = ingest_file(self.connection, "owner", "assignment2.txt", b"Question 4: recursion requires a base case.")

    def test_exact_filename_and_stable_id_reads_are_deterministic_read_only(self):
        self.connection.execute("PRAGMA query_only=ON")
        reference = detect_file_reference(self.connection, "owner", "What does assignment2.txt say about question 4?")
        self.assertEqual(reference["method"], "exact_filename")
        result = retrieve_file_context(self.connection, "owner", reference["selection"])
        self.assertIn("base case", result["chunks"][0]["text"])
        self.assertEqual(result["files"][0]["file_id"], self.file["file_id"])
        self.assertEqual(detect_file_reference(self.connection, "owner", "Exams this week"), None)

    def test_query_matches_chunk_text_not_only_filename(self):
        result = retrieve_file_context(self.connection, "owner", {"query": "recursion assignment"})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["files"][0]["filename"], "assignment2.txt")
        self.assertEqual(retrieve_file_context(self.connection, "owner", {"query": "nonexistent-topic"})["count"], 0)

    def test_duplicate_names_do_not_silently_choose_or_blend_uploads(self):
        second = ingest_file(self.connection, "owner", "assignment2.txt", b"An entirely different file.")
        reference = detect_file_reference(self.connection, "owner", "Read assignment2.txt")
        self.assertEqual(reference["method"], "ambiguous_filename")
        result = retrieve_file_context(self.connection, "owner", reference["selection"])
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["chunks"], [])
        selected = retrieve_file_context(self.connection, "owner", {"file_ids": [second["file_id"]]})
        self.assertEqual(selected["count"], 1)
        self.assertIn("different", selected["chunks"][0]["text"])
        explicit = detect_file_reference(self.connection, "owner", f'Read assignment2.txt, ID {second["file_id"]}')
        self.assertEqual(explicit["method"], "explicit_id")
        self.assertEqual(explicit["selection"]["file_ids"], [second["file_id"]])

    def test_large_file_ranks_relevant_later_chunk_and_bounds_payload(self):
        large = ingest_file(self.connection, "owner", "large.txt", ("Other material. " * 8000 + "\nQuestion 4 recursion answer.").encode())
        result = retrieve_file_context(self.connection, "owner", {"file_ids": [large["file_id"]], "query": "question 4 recursion"})
        self.assertLessEqual(len(result["chunks"]), MAX_CONTEXT_CHUNKS)
        self.assertLessEqual(sum(len(item["text"]) for item in result["chunks"]), MAX_CONTEXT_CHARS)
        self.assertTrue(result["truncated"])
        self.assertIn("recursion answer", json.dumps(result))

    def test_no_cross_owner_lookup_even_with_known_identifier(self):
        self.assertEqual(retrieve_file_context(self.connection, "other", {"file_ids": [self.file["file_id"]]})["count"], 0)
        self.assertEqual(retrieve_file_context(self.connection, "other", {"query": "recursion"})["count"], 0)

    def test_unknown_name_and_single_recent_reference(self):
        unknown = detect_file_reference(self.connection, "owner", "What does missing.pdf say?")
        self.assertEqual(retrieve_file_context(self.connection, "owner", unknown["selection"])["count"], 0)
        ref = detect_file_reference(self.connection, "owner", "Explain that file", [self.file["file_id"]])
        self.assertEqual(ref["selection"]["file_ids"], [self.file["file_id"]])
        self.assertIsNone(detect_file_reference(self.connection, "owner", "that PDF", [self.file["file_id"], "file_" + "a" * 32]))

    def test_paths_urls_unbounded_or_extra_requests_rejected(self):
        for value in ({"query": "/etc/passwd"}, {"query": "read ../secret"}, {"query": "https://example.test"},
                      {"query": "backend/private.txt"}, {"query": "C:private.txt"},
                      {"filename": "../file.txt"}, {"file_ids": ["/etc/passwd"]}, {"query": "x" * 301},
                      {"query": "recursion", "path": "/tmp/file"}, {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                FileSelection.model_validate(value)


if __name__ == "__main__":
    unittest.main()
