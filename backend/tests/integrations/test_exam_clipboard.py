"""Pasted exam import checks; only temporary/in-memory SQLite data is written."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import database
from backend.app.api import common, exams as exam_api
from backend.app.integrations import exam_clipboard as importer
from backend.app.planner import exams

TABLE = """| Course (Class Number) | Course Title | Exam Date | Time | Campus | Room | Book |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| PHYSICS 140 (55267) | Digital Fundamentals | Mon 02 Nov 2026 | 09:00 - 11:15 | City | TBA | Closed Book |
| ECON 151G (55074) | Understandg the Global Econ | Fri 06 Nov 2026 | 09:00 - 11:15 | City | TBA | Restricted Book - Written upon |
| MATHS 102 (53497) | Functioning in Mathematics | Fri 06 Nov 2026 | 14:00 - 16:30 | City | TBA | Restricted Book - Written upon |
| COMPSCI 130 (56456) | Intro to Software Fundamentals | Tue 10 Nov 2026 | 14:00 - 16:30 | City | TBA | Restricted Book - Written upon |"""

# A browser copy may use tabs per row or one line per cell, with no Markdown.
COPIED_ROWS = [[cell.strip() for cell in line.strip("|").split("|")]
               for line in TABLE.splitlines() if not line.startswith("| :---")]
TABBED_TABLE = "\n".join("\t".join(row) for row in COPIED_ROWS)
LINE_TABLE = "\n".join(cell for row in COPIED_ROWS for cell in row)


class ExamClipboardTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(database.sql_file.read_text())
        self.addCleanup(self.connection.close)

    def test_exact_four_exam_table(self):
        rows = importer.parse_exam_table(TABLE)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {
            "name": "PHYSICS 140 Exam", "category": "University", "subject": "PHYSICS 140",
            "date": "2026-11-02", "start_time": "09:00", "end_time": "11:15",
        })
        self.assertEqual([row["date"] for row in rows], ["2026-11-02", "2026-11-06", "2026-11-06", "2026-11-10"])
        self.assertEqual(rows[-1]["subject"], "COMPSCI 130")
        self.assertEqual(rows[-1]["start_time"], "14:00")
        self.assertEqual(rows[-1]["end_time"], "16:30")
        self.assertEqual(exams.get_all_exams(self.connection), [])

    def test_reordered_columns_iso_dates_and_empty_optional_cells(self):
        table = """Time | Course (Class Number) | Exam Date | Book
--- | --- | --- | ---
 | PHYSICS 140 (55267) | 2026-11-02 | """
        row = importer.parse_exam_table(table)[0]
        self.assertEqual(row["date"], "2026-11-02")
        self.assertIsNone(row["start_time"])
        self.assertIsNone(row["end_time"])

    def test_code_fence_escaped_pipe_and_unicode_time_dash(self):
        table = TABLE.replace("Digital Fundamentals", r"Digital \| Fundamentals").replace("09:00 - 11:15", "09:00 – 11:15")
        self.assertEqual(importer.parse_exam_table(f"```markdown\n{table}\n```"), importer.parse_exam_table(TABLE))

    def test_browser_copies_with_and_without_headers_match_markdown_preview(self):
        expected = importer.parse_exam_table(TABLE)
        for text in (TABBED_TABLE, LINE_TABLE,
                     "\n".join(TABBED_TABLE.splitlines()[1:]),
                     "\n".join(LINE_TABLE.splitlines()[7:]),
                     LINE_TABLE.replace("\n", "\n\n")):
            with self.subTest(text=text):
                self.assertEqual(importer.parse_exam_table(text), expected)
        self.assertEqual(exams.get_all_exams(self.connection), [])

    def test_tabbed_rows_preserve_empty_cells_and_reordered_headers(self):
        text = "Time\tCourse (Class Number)\tExam Date\tBook\n\tPHYSICS 140 (55267)\t2026-11-02\t"
        row = importer.parse_exam_table(text)[0]
        self.assertIsNone(row["start_time"])
        self.assertIsNone(row["end_time"])
        self.assertEqual(row["subject"], "PHYSICS 140")
        with self.subTest(format="date-only lines"):
            row = importer.parse_exam_table(LINE_TABLE.replace("09:00 - 11:15", "TBA"))[0]
            self.assertIsNone(row["start_time"])
            self.assertIsNone(row["end_time"])

    def test_incomplete_or_misaligned_website_copies_are_rejected(self):
        invalid_tables = (
            "\n".join(LINE_TABLE.splitlines()[:-1]),
            LINE_TABLE.replace("Digital Fundamentals\n", ""),
            LINE_TABLE.replace("PHYSICS 140 (55267)", "TBA"),
            LINE_TABLE.replace("Mon 02 Nov 2026", "Tue 02 Nov 2026"),
            LINE_TABLE.replace("Course Title", "Wrong header"),
            TABBED_TABLE.replace("Digital Fundamentals\t", ""),
            TABBED_TABLE.splitlines()[0],
            "Course (Class Number)\nCourse Title\nExam Date\nTime\nCampus\nRoom\nBook",
        )
        for text in invalid_tables:
            with self.subTest(text=text), self.assertRaises(importer.ExamTableError):
                importer.parse_exam_table(text)

    def test_website_copy_limits_and_storage_use_existing_pipeline(self):
        with self.assertRaises(importer.ExamTableError):
            importer.parse_exam_table("\n".join(["\n".join(LINE_TABLE.splitlines()[7:14])] * 101))
        prepared = importer.prepare_exam_import(importer.parse_exam_table(LINE_TABLE))
        self.assertEqual(importer.save_exam_import(self.connection, prepared),
                         {"imported": 4, "duplicates_skipped": 0})
        self.assertEqual(importer.save_exam_import(self.connection, prepared),
                         {"imported": 0, "duplicates_skipped": 4})

    def test_invalid_rows_are_not_silently_dropped(self):
        for table in (
            TABLE.replace("Mon 02 Nov 2026", "Tue 02 Nov 2026"),
            TABLE.replace("Mon 02 Nov 2026", "Mon 31 Nov 2026"),
            TABLE.replace("09:00 - 11:15", "25:00 - 26:00"),
            TABLE.replace("09:00 - 11:15", "11:15 - 09:00"),
            TABLE.replace("PHYSICS 140 (55267)", ""),
            TABLE.replace("Digital Fundamentals |", "Digital Fundamentals | Extra |"),
        ):
            with self.subTest(table=table), self.assertRaises(importer.ExamTableError) as caught:
                importer.parse_exam_table(table)
            self.assertIn("Exam row 1:", str(caught.exception))

    def test_missing_header_separator_and_oversized_batch(self):
        for table in ("", "not a table", TABLE.replace("Exam Date", "Day"), TABLE.replace(":---", "separator", 1),
                      "\n".join(TABLE.splitlines()[:2] + [TABLE.splitlines()[2]] * 101)):
            with self.subTest(table=table), self.assertRaises(importer.ExamTableError):
                importer.parse_exam_table(table)

    def test_import_reuses_add_exam_and_skips_existing_and_batch_duplicates(self):
        prepared = importer.prepare_exam_import(importer.parse_exam_table(TABLE))
        with patch.object(exams, "add_exam", wraps=exams.add_exam) as add:
            result = importer.save_exam_import(self.connection, prepared + [prepared[0]])
            self.assertEqual(add.call_count, 4)
            self.assertFalse(add.call_args.kwargs["commit"])
        self.assertEqual(result, {"imported": 4, "duplicates_skipped": 1})
        before = exams.get_all_exams(self.connection)
        self.assertEqual(len(before), 4)
        self.assertTrue(all(row[7] == "Manual" and row[8] is None for row in before))
        self.assertEqual(importer.save_exam_import(self.connection, prepared), {"imported": 0, "duplicates_skipped": 4})
        self.assertEqual(before, exams.get_all_exams(self.connection))

    def test_whole_batch_rolls_back_if_an_insert_fails(self):
        prepared = importer.prepare_exam_import(importer.parse_exam_table(TABLE))
        original_add = exams.add_exam
        count = 0
        def failing_add(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise sqlite3.OperationalError("Injected insert failure")
            return original_add(*args, **kwargs)
        with patch.object(exams, "add_exam", side_effect=failing_add), self.assertRaises(sqlite3.Error):
            importer.save_exam_import(self.connection, prepared)
        self.assertEqual(exams.get_all_exams(self.connection), [])

    def test_existing_standalone_add_still_commits(self):
        columns, values = importer.prepare_exam_import(importer.parse_exam_table(TABLE))[0]
        exams.add_exam(self.connection, columns, values)
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(len(exams.get_all_exams(self.connection)), 1)


class ExamClipboardAPITests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(exam_api.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_preview_and_invalid_import_never_open_database(self):
        rows = importer.parse_exam_table(TABLE)
        with patch.object(common, "create_connection") as connect:
            preview = self.client.post("/exams/import/preview", json={"text": TABLE})
            invalid = self.client.post("/exams/import", json={"exams": [rows[0], {**rows[1], "date": "invalid"}]})
            metadata = self.client.post("/exams/import", json={"exams": [{**rows[0], "source": "Canvas"}]})
            empty = self.client.post("/exams/import", json={"exams": []})
        connect.assert_not_called()
        self.assertEqual(preview.json(), {"exams": rows})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(metadata.status_code, 422)
        self.assertEqual(empty.status_code, 422)

    def test_website_copies_are_supported_by_existing_read_only_preview_endpoint(self):
        with patch.object(common, "create_connection") as connect:
            for text in (TABBED_TABLE, LINE_TABLE):
                response = self.client.post("/exams/import/preview", json={"text": text})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"exams": importer.parse_exam_table(TABLE)})
            invalid = self.client.post("/exams/import/preview", json={"text": "\n".join(LINE_TABLE.splitlines()[:-1])})
            self.assertEqual(invalid.status_code, 400)
            self.assertIn("incomplete", invalid.json()["detail"])
        connect.assert_not_called()

    def test_reviewed_correction_is_saved_and_returned_by_existing_list_endpoint(self):
        rows = importer.parse_exam_table(TABLE)
        rows[0]["name"] = "Physics final exam"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            with sqlite3.connect(path) as connection:
                connection.executescript(database.sql_file.read_text())
            with patch.object(common, "create_connection", side_effect=lambda: sqlite3.connect(path)):
                response = self.client.post("/exams/import", json={"exams": rows})
                listing = self.client.get("/exams")
                repeated = self.client.post("/exams/import", json={"exams": rows})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"imported": 4, "duplicates_skipped": 0})
        self.assertEqual(listing.json()[0]["name"], "Physics final exam")
        self.assertEqual(listing.json()[0]["source"], "Manual")
        self.assertIsNone(listing.json()[0]["external_id"])
        self.assertEqual(repeated.json(), {"imported": 0, "duplicates_skipped": 4})


if __name__ == "__main__":
    unittest.main()
