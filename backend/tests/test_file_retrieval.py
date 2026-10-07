"""Read-only file context, isolation, deterministic matching and hard limits."""

import json
import sqlite3
import unittest
from unittest.mock import patch

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

    def test_case_insensitive_exact_names_punctuation_and_generic_words(self):
        for message in ("Can you summarise ASSIGNMENT2.TXT?", "Read 'assignment2.txt'.", "Read assignment2.txt."):
            with self.subTest(message=message):
                reference = detect_file_reference(self.connection, "owner", message)
                self.assertEqual(reference["method"], "exact_filename")
                self.assertEqual(reference["selection"]["file_ids"], [self.file["file_id"]])
        for message in ("How do PDF files work?", "Explain notes", "What is an assignment?",
                        "Read xassignment2.txt", "Read assignment2.txt.bak"):
            with self.subTest(message=message):
                reference = detect_file_reference(self.connection, "owner", message)
                self.assertTrue(reference is None or reference["method"] == "unknown_filename")
                if reference:
                    self.assertEqual(retrieve_file_context(self.connection, "owner", reference["selection"])["count"], 0)

    def test_duplicate_name_reuses_only_unique_current_chat_reference(self):
        second = ingest_file(self.connection, "owner", "Assignment2.TXT", b"Another assignment.")
        reference = detect_file_reference(self.connection, "owner", "Use assignment2.txt", [second["file_id"]])
        self.assertEqual(reference["method"], "filename_chat_reference")
        self.assertEqual(reference["selection"]["file_ids"], [second["file_id"]])
        result = retrieve_file_context(self.connection, "owner", reference["selection"])
        self.assertIn("Another assignment", result["chunks"][0]["text"])
        for refs in ([self.file["file_id"], second["file_id"]], ["file_" + "a" * 32], []):
            with self.subTest(refs=refs):
                reference = detect_file_reference(self.connection, "owner", "Use assignment2.txt", refs)
                self.assertEqual(reference["method"], "ambiguous_filename")
                self.assertEqual(retrieve_file_context(self.connection, "owner", reference["selection"])["chunks"], [])

    def test_paths_and_unknown_names_never_open_the_filesystem(self):
        with patch("builtins.open", side_effect=AssertionError("No filesystem reading allowed")) as opened:
            for message in ("read ../../assignment2.txt", "read assignment2.txt/secret", "read C:assignment2.txt",
                            "read https://example.test/assignment2.txt", "read /tmp/assignment2.txt"):
                with self.subTest(message=message):
                    self.assertIsNone(detect_file_reference(self.connection, "owner", message))
            unknown = detect_file_reference(self.connection, "owner", "Use missing.pdf")
            self.assertEqual(unknown["method"], "unknown_filename")
            result = retrieve_file_context(self.connection, "owner", unknown["selection"])
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["files"], [])
            opened.assert_not_called()

    def test_owned_file_with_no_readable_chunks_is_empty_with_metadata(self):
        self.connection.execute("UPDATE imported_file_chunks SET text='   ' WHERE file_id=?", (self.file["file_id"],))
        self.connection.commit()
        self.connection.execute("PRAGMA query_only=ON")
        reference = detect_file_reference(self.connection, "owner", "Read assignment2.txt")
        result = retrieve_file_context(self.connection, "owner", reference["selection"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["chunks"], [])
        self.assertEqual(result["files"][0]["file_id"], self.file["file_id"])

    def test_pdf_page_metadata_and_small_file_content_are_preserved(self):
        pdf = storage.save_file(self.connection, "owner", {"filename": "assignment2.pdf", "file_type": "pdf",
            "text": "Page 2 context. Question 4 needs recursion.", "chunks": [
                {"text": "Page 2 context.", "page": 2, "section": None},
                {"text": "Question 4 needs recursion.", "page": 3, "section": None}]})
        reference = detect_file_reference(self.connection, "owner", "What does assignment2.pdf say about question 4?")
        result = retrieve_file_context(self.connection, "owner", reference["selection"])
        self.assertEqual(result["files"][0]["file_id"], pdf["file_id"])
        self.assertEqual([chunk["page"] for chunk in result["chunks"]], [2, 3])
        self.assertFalse(result["truncated"])
        self.assertNotIn("path", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
