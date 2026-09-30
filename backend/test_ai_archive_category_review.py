"""Offline Stage 4.5 tests; no paid model calls or archive writes."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import ai_archive_category_review as review, ai_memory
from backend.app.ai_archive_summary import BASE_ARCHIVE_CATEGORIES


def stage4(items, *, refs=None, keywords=None):
    refs = [] if refs is None else refs
    categories = {
        name: {"summary": [], "keywords": []} for name in BASE_ARCHIVE_CATEGORIES
    }
    categories["general"] = {
        "summary": items,
        "keywords": [] if keywords is None else keywords,
    }
    return {
        "success": True,
        "categories": categories,
        "needs_category_review": bool(refs),
        "uncategorized_item_refs": refs,
        "source_turn_count": 3,
        "source_turn_refs": [{"source_index": 0, "timestamp": None}],
    }


def proposal(name, refs, topics):
    return {
        "needs_new_category": True,
        "proposed_category": name,
        "reason": "A recurring broad topic needs its own retrieval category.",
        "example_topics": topics,
        "item_refs": refs,
    }


class ArchiveCategoryReviewTests(unittest.TestCase):
    def setUp(self):
        key_patch = patch.object(review, "is_openai_api_key_configured", return_value=True)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        env_patch = patch.dict(review.os.environ, {"OPENAI_API_KEY": "test-key"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        client_patch = patch.object(review, "OpenAI")
        self.openai = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client = self.openai.return_value.__enter__.return_value

    def set_response(self, value, *, status="completed"):
        self.client.responses.parse.return_value = SimpleNamespace(
            status=status, output_parsed=value,
        )

    def test_example_a_career_is_accepted_and_only_selected_items_move(self):
        data = stage4(
            ["Discussed internship applications.", "Reviewed CV preparation.",
             "Talked about a one-off film."],
            refs=[0, 1, 2], keywords=["internships", "CV preparation", "film"],
        )
        before = deepcopy(data)
        self.set_response(proposal("career", [0, 1], ["internships", "CV preparation"]))
        result = review.review_archive_summary_categories(data)

        self.assertEqual(data, before)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["category_added"], "career")
        self.assertEqual(result["reclassified_item_refs"], [0, 1])
        self.assertEqual(result["summary"]["categories"]["career"]["summary"],
                         before["categories"]["general"]["summary"][:2])
        self.assertEqual(result["summary"]["categories"]["general"]["summary"],
                         ["Talked about a one-off film."])
        self.assertEqual(result["summary"]["categories"]["general"]["keywords"],
                         ["film"])
        self.assertEqual(result["summary"]["source_turn_refs"], before["source_turn_refs"])

        call = self.client.responses.parse.call_args.kwargs
        payload = json.loads(call["input"][0]["content"])
        self.assertEqual(list(payload), ["existing_categories", "unresolved_general_items"])
        self.assertEqual(payload["existing_categories"], list(BASE_ARCHIVE_CATEGORIES))
        self.assertEqual([item["item_ref"] for item in payload["unresolved_general_items"]],
                         [0, 1, 2])
        self.assertNotIn("source_turn_refs", str(payload))
        self.assertNotIn("test-key", str(payload))
        self.assertEqual(call["text_format"], review.ArchiveCategoryProposal)
        self.assertFalse(call["store"])

    def test_examples_b_and_c_existing_categories_skip_review(self):
        for content in (
            ["Canvas API error", "FastAPI import issue"],
            ["Preparing for quizzes", "Exam study plan"],
        ):
            with self.subTest(content=content):
                result = review.review_archive_summary_categories(stage4(content))
                self.assertEqual(result["status"], "not_needed")
                self.assertEqual(result["category_added"], None)
        self.openai.assert_not_called()

    def test_pipeline_calls_stage_four_then_skips_review_when_not_flagged(self):
        data = stage4(["A one-off discussion."])
        with patch.object(review, "summarize_compactable_archive_turns",
                          return_value=data) as summarize:
            result = review.summarize_and_review_compactable_archive_turns(["candidate"])
        summarize.assert_called_once_with(["candidate"])
        self.assertEqual(result["status"], "not_needed")
        self.openai.assert_not_called()

    def test_existing_category_synonyms_and_narrow_names_are_rejected(self):
        data = stage4(["Discussion one", "Discussion two"], refs=[0, 1])
        for name in ("exam", "exam_prep", "debugging", "canvas_import_bug",
                     "calendar_planning", "goals", "preferences", "project_architecture",
                     "my_career_plan_for_2027", "random_other_things", "exam2_notes",
                     "Career", "career advice"):
            with self.subTest(name=name):
                self.set_response(proposal(name, [0, 1], ["one", "two"]))
                result = review.review_archive_summary_categories(data)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["summary"], data)

    def test_example_d_one_travel_item_has_weak_evidence(self):
        data = stage4(["I might travel during summer."], refs=[0])
        result = review.review_archive_summary_categories(data)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["summary"]["categories"]["general"]["summary"],
                         data["categories"]["general"]["summary"])
        self.openai.assert_not_called()

    def test_example_e_repeated_travel_is_accepted(self):
        data = stage4(["Compared flights and hotels.", "Discussed itinerary destinations."],
                      refs=[0, 1])
        self.set_response(proposal("travel", [0, 1], ["flights", "itinerary"]))
        result = review.review_archive_summary_categories(data)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["summary"]["categories"]["travel"]["summary"],
                         data["categories"]["general"]["summary"])
        self.assertEqual(result["summary"]["categories"]["general"]["summary"], [])

    def test_example_f_protected_content_fails_before_model_call(self):
        data = stage4(["My goal is to graduate next year.", "Internship applications."],
                      refs=[0, 1])
        result = review.review_archive_summary_categories(data)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Protected memory", result["reason"])
        self.assertEqual(result["summary"], data)
        self.openai.assert_not_called()

    def test_llm_can_decline_new_category(self):
        data = stage4(["Canvas API error", "FastAPI import issue"], refs=[0, 1])
        self.set_response({
            "needs_new_category": False, "proposed_category": None,
            "reason": "These fit technical_issues.", "example_topics": [], "item_refs": [],
        })
        result = review.review_archive_summary_categories(data)
        self.assertEqual(result["status"], "not_needed")
        self.assertEqual(result["summary"], data)

    def test_invalid_refs_and_schema_leave_general_unchanged(self):
        data = stage4(["Internships", "CVs", "Hotels"], refs=[0, 1])
        invalid = (
            proposal("career", [0], ["internships"]),
            proposal("career", [0, 2], ["internships", "hotels"]),
            {**proposal("career", [0, 1], ["internships"]), "extra": "bad"},
            {**proposal("career", [0, 1], ["internships"]),
             "needs_new_category": "true"},
            {**proposal("career", [0, 1], ["internships"]), "item_refs": [0, 0]},
        )
        for output in invalid:
            with self.subTest(output=output):
                self.set_response(output)
                result = review.review_archive_summary_categories(data)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["summary"], data)

    def test_selected_items_must_match_the_proposed_topics(self):
        data = stage4(["Discussed internships.", "Talked about hotels."], refs=[0, 1])
        self.set_response(proposal("career", [0, 1], ["internships", "job applications"]))
        result = review.review_archive_summary_categories(data)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["summary"], data)

    def test_api_failure_or_missing_key_never_changes_summary(self):
        data = stage4(["Internships", "CVs"], refs=[0, 1])
        review.is_openai_api_key_configured.return_value = False
        self.assertEqual(review.review_archive_summary_categories(data)["summary"], data)
        self.openai.assert_not_called()

        review.is_openai_api_key_configured.return_value = True
        self.client.responses.parse.side_effect = TimeoutError("unavailable")
        self.assertEqual(review.review_archive_summary_categories(data)["status"], "rejected")
        self.client.responses.parse.side_effect = None
        self.set_response(proposal("career", [0, 1], ["internships"]), status="incomplete")
        self.assertEqual(review.review_archive_summary_categories(data)["status"], "rejected")

    def test_archive_file_is_not_read_or_written(self):
        data = stage4(["Internships", "CV preparation"], refs=[0, 1])
        self.set_response(proposal("career", [0, 1], ["internships", "CV preparation"]))
        with tempfile.TemporaryDirectory() as directory:
            archive_file = Path(directory) / "archive.jsonl"
            archive_file.write_text("existing private archive\n", encoding="utf-8")
            original = archive_file.read_bytes()
            with patch.object(ai_memory, "ARCHIVE_FILE", archive_file), \
                    patch.object(ai_memory, "_iter_archived_turns",
                                 side_effect=AssertionError("archive read")):
                result = review.review_archive_summary_categories(data)
            self.assertEqual(result["status"], "accepted")
            self.assertEqual(archive_file.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
