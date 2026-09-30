"""Offline Stage 4 tests; OpenAI is mocked and archive files are untouched."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import ai_archive_summary as summary, ai_memory


MANUAL_CASES = (
    "Tomorrow I have a tutorial from 2 PM to 3 PM.",
    "I have a COMPSCI test next week.",
    "We were learning recursion and how numbers[1:] works.",
    "My FastAPI server failed because uvicorn was not installed.",
    "Thanks, that makes sense.",
)


def classified(user, *, status="compactable", timestamp="2026-09-30T10:00:00+00:00",
               assistant="Assistant response", candidate_index=None):
    return {
        "status": status,
        "candidate_index": candidate_index,
        "archived_turn": {
            "session_id": "test-session",
            "timestamp": timestamp,
            "turn": {"user": user, "assistant": {"message": assistant, "actions": []}},
        },
    }


def categories(**overrides):
    result = {
        name: {"summary": [], "keywords": []}
        for name in ("activities", "exams_tests", "study_topics",
                     "technical_issues", "general")
    }
    result.update(overrides)
    return result


class ArchiveSummaryTests(unittest.TestCase):
    def setUp(self):
        key_patch = patch.object(summary, "is_openai_api_key_configured", return_value=True)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        env_patch = patch.dict(summary.os.environ, {"OPENAI_API_KEY": "test-key"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        client_patch = patch.object(summary, "OpenAI")
        self.openai = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client = self.openai.return_value.__enter__.return_value

    def set_response(self, value, *, status="completed"):
        if isinstance(value, dict) and "needs_category_review" not in value:
            value = {**value, "needs_category_review": False,
                     "uncategorized_item_refs": []}
        self.client.responses.parse.return_value = SimpleNamespace(
            status=status, output_parsed=value,
        )

    def test_only_compactable_turns_are_sent_and_metadata_is_calculated_in_python(self):
        entries = [
            classified("Remember this long-term goal", status="protected"),
            classified("Study recursion for a COMPSCI test", timestamp="2026-09-30T22:00:00+12:00",
                       assistant="Reviewed recursive lists and test preparation.", candidate_index=4),
            classified("Python indentation error", timestamp="2026-09-29T08:00:00+00:00"),
            classified("Maybe this matters later", status="uncertain"),
        ]
        original = deepcopy(entries)
        model_categories = categories(
            study_topics={"summary": ["Practiced recursive list processing."],
                          "keywords": ["recursion", "list slicing"]},
            exams_tests={"summary": ["Discussed COMPSCI test preparation."],
                         "keywords": ["COMPSCI test"]},
            technical_issues={"summary": ["Resolved a Python indentation error."],
                              "keywords": ["Python indentation"]},
        )
        self.set_response(model_categories)

        with patch.object(summary, "_logger") as logger:
            result = summary.summarize_compactable_archive_turns(entries)

        self.assertEqual(entries, original)
        self.assertTrue(result["success"])
        self.assertEqual(result["source_turn_count"], 2)
        self.assertEqual(result["period_start"], "2026-09-29T08:00:00+00:00")
        self.assertEqual(result["period_end"], "2026-09-30T10:00:00+00:00")
        self.assertEqual(result["categories"], model_categories)
        self.assertEqual(
            result["source_turn_refs"],
            [
                {"source_index": 1, "session_id": "test-session",
                 "timestamp": "2026-09-30T22:00:00+12:00", "candidate_index": 4},
                {"source_index": 2, "session_id": "test-session",
                 "timestamp": "2026-09-29T08:00:00+00:00", "candidate_index": None},
            ],
        )
        logger.warning.assert_called_once_with(
            "Excluded %d non-compactable archive candidates from Stage 4.", 2,
        )

        call = self.client.responses.parse.call_args.kwargs
        payload = json.loads(call["input"][0]["content"])
        self.assertEqual(list(payload), ["compactable_turns"])
        self.assertEqual([item["source_index"] for item in payload["compactable_turns"]], [1, 2])
        self.assertNotIn("Remember this long-term goal", str(payload))
        self.assertNotIn("Maybe this matters later", str(payload))
        self.assertNotIn("test-key", str(payload))
        self.assertEqual(call["text_format"], summary.ArchiveCategorizedSummary)
        self.assertEqual(call["model"], summary.ARCHIVE_SUMMARY_MODEL)
        self.assertEqual(call["reasoning"], {"effort": "none"})
        self.assertFalse(call["store"])

    def test_empty_categories_are_kept_and_no_timestamps_are_invented(self):
        self.set_response(categories(general={"summary": [], "keywords": []}))
        result = summary.summarize_compactable_archive_turns([
            classified("Thanks, that makes sense.", timestamp=None),
        ])
        self.assertTrue(result["success"])
        self.assertEqual(result["period_start"], None)
        self.assertEqual(result["period_end"], None)
        self.assertEqual(result["source_turn_refs"][0]["timestamp"], None)
        self.assertEqual(set(result["categories"]), set(categories()))
        self.assertTrue(all(value == {"summary": [], "keywords": []}
                            for value in result["categories"].values()))

    def test_legacy_turn_level_timestamp_is_preserved(self):
        entry = classified("A temporary question", timestamp=None)
        entry["archived_turn"]["turn"]["timestamp"] = "2026-09-29T08:00:00+00:00"
        self.set_response(categories())
        result = summary.summarize_compactable_archive_turns([entry])
        self.assertEqual(result["period_start"], "2026-09-29T08:00:00+00:00")
        self.assertEqual(result["period_end"], "2026-09-29T08:00:00+00:00")
        self.assertEqual(result["source_turn_refs"][0]["timestamp"],
                         "2026-09-29T08:00:00+00:00")

    def test_all_non_compactable_or_empty_input_skips_model(self):
        with patch.object(summary, "_logger"):
            result = summary.summarize_compactable_archive_turns([
                classified("Important decision", status="protected"),
            ])
        self.assertTrue(result["success"])
        self.assertEqual(result["source_turn_count"], 0)
        self.assertEqual(result["categories"], categories())
        self.assertEqual(result["source_turn_refs"], [])
        self.openai.assert_not_called()

    def test_bad_model_schema_fails_without_saving_partial_summary(self):
        good = categories()
        bad_outputs = (
            {name: value for name, value in good.items() if name != "general"},
            {**good, "goals": {"summary": [], "keywords": []}},
            {**good, "activities": {"summary": "not a list", "keywords": []}},
            {**good, "exams_tests": {"summary": [], "keywords": [""]}},
            {**good, "technical_issues": {"summary": ["x" * 241], "keywords": []}},
            {**good, "source_turn_refs": ["invented"]},
        )
        for output in bad_outputs:
            with self.subTest(output=output):
                self.set_response(output)
                result = summary.summarize_compactable_archive_turns([
                    classified("A temporary issue"),
                ])
                self.assertEqual(result["success"], False)
                self.assertNotIn("categories", result)

    def test_api_failure_missing_key_and_incomplete_response_fail_safely(self):
        entry = classified("Python error")
        summary.is_openai_api_key_configured.return_value = False
        result = summary.summarize_compactable_archive_turns([entry])
        self.assertFalse(result["success"])
        self.openai.assert_not_called()

        summary.is_openai_api_key_configured.return_value = True
        self.client.responses.parse.side_effect = TimeoutError("API timeout")
        self.assertFalse(summary.summarize_compactable_archive_turns([entry])["success"])
        self.client.responses.parse.side_effect = None
        self.set_response(categories(), status="incomplete")
        self.assertFalse(summary.summarize_compactable_archive_turns([entry])["success"])
        self.client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=None,
        )
        self.assertFalse(summary.summarize_compactable_archive_turns([entry])["success"])

    def test_invalid_compactable_record_fails_before_model_call(self):
        result = summary.summarize_compactable_archive_turns([
            {"status": "compactable", "archived_turn": {"timestamp": "2026-01-01"}},
        ])
        self.assertFalse(result["success"])
        self.openai.assert_not_called()

    def test_real_archive_file_is_not_read_or_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_file = Path(directory) / "archive.jsonl"
            archive_file.write_text("existing archive content\n", encoding="utf-8")
            original_bytes = archive_file.read_bytes()
            self.set_response(categories())
            with patch.object(ai_memory, "ARCHIVE_FILE", archive_file), \
                    patch.object(ai_memory, "_iter_archived_turns",
                                 side_effect=AssertionError("archive reread")):
                result = summary.summarize_compactable_archive_turns([
                    classified("One-off question"),
                ])
            self.assertTrue(result["success"])
            self.assertEqual(archive_file.read_bytes(), original_bytes)

    def test_manual_examples_can_fill_only_the_fixed_categories(self):
        self.set_response(categories(
            activities={"summary": ["Discussed a tutorial from 2–3 PM."],
                        "keywords": ["tutorial", "activity"]},
            exams_tests={"summary": ["Discussed a COMPSCI test next week."],
                         "keywords": ["COMPSCI test"]},
            study_topics={"summary": ["Reviewed recursion and list slicing."],
                          "keywords": ["recursion", "numbers[1:]"]},
            technical_issues={"summary": ["Resolved a missing uvicorn dependency."],
                              "keywords": ["FastAPI", "uvicorn"]},
        ))
        result = summary.summarize_compactable_archive_turns([
            classified(text) for text in MANUAL_CASES
        ])
        self.assertTrue(result["success"])
        self.assertEqual(set(result["categories"]), set(categories()))
        self.assertEqual(result["categories"]["general"], {"summary": [], "keywords": []})
        self.assertEqual(result["source_turn_count"], 5)

    def test_stage_four_flags_only_selected_general_items_for_review(self):
        self.set_response({
            **categories(general={
                "summary": ["Discussed internship applications.", "Discussed CV preparation."],
                "keywords": ["internships", "CV"],
            }),
            "needs_category_review": True,
            "uncategorized_item_refs": [0, 1],
        })
        result = summary.summarize_compactable_archive_turns([
            classified("What about internships and CVs?"),
        ])
        self.assertTrue(result["success"])
        self.assertEqual(result["uncategorized_item_refs"], [0, 1])
        self.assertTrue(result["needs_category_review"])
        self.assertEqual(set(result["categories"]), set(summary.BASE_ARCHIVE_CATEGORIES))

    def test_stage_four_rejects_invalid_review_refs(self):
        general = categories(general={"summary": ["Travel discussion."], "keywords": []})
        invalid = (
            {**general, "needs_category_review": True, "uncategorized_item_refs": []},
            {**general, "needs_category_review": False, "uncategorized_item_refs": [0]},
            {**general, "needs_category_review": True, "uncategorized_item_refs": [1]},
            {**general, "needs_category_review": True, "uncategorized_item_refs": [0, 0]},
        )
        for output in invalid:
            with self.subTest(output=output):
                self.set_response(output)
                result = summary.summarize_compactable_archive_turns([
                    classified("Travel discussion"),
                ])
                self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
