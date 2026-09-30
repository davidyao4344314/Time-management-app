"""Offline tests for read-only Stage 2.5 archive candidate classification."""

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import ai_memory
from backend.app.ai_archive_protection import (
    classify_archive_candidate,
    classify_compaction_candidates,
)


def archived_turn(user, assistant="Response", *, timestamp="2026-01-01T00:00:00+00:00"):
    return {
        "session_id": "test-session",
        "timestamp": timestamp,
        "turn": {"user": user, "assistant": {"message": assistant, "actions": []}},
    }


class ArchiveProtectionTests(unittest.TestCase):
    def test_requested_examples(self):
        examples = (
            ("Remember this: I want recent memory to keep the last 5 turns.",
             "protected", "explicit_memory"),
            ("From now on, imported activities should keep their source.",
             "protected", "preference"),
            ("My long-term goal is to finish the study planner.",
             "protected", "goal"),
            ("We decided the LLM should never write SQL directly.",
             "protected", "decision"),
            ("I want to understand this Python recursion question.",
             "uncertain", None),
            ("This is important, why is my loop broken?", "uncertain", None),
            ("Can you explain what a queue is?", "compactable", None),
            ("Maybe I should change the architecture later.", "uncertain", None),
        )
        for user, expected_status, expected_category in examples:
            with self.subTest(user=user):
                result = classify_archive_candidate(archived_turn(user))
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["category"], expected_category)
                self.assertIsNotNone(result["matched_rule"])

    def test_both_sides_case_insensitive_and_no_single_word_protection(self):
        assistant_decision = classify_archive_candidate(
            archived_turn("Okay", "WE AGREED to keep this requirement."),
        )
        self.assertEqual(assistant_decision["status"], "protected")
        self.assertEqual(assistant_decision["category"], "decision")

        for user in (
            "What does goal mean in this code?",
            "This class is called ImportantError.",
            "Can you explain ImportantError?",
        ):
            with self.subTest(user=user):
                self.assertNotEqual(
                    classify_archive_candidate(archived_turn(user))["status"],
                    "protected",
                )

        action_only = archived_turn("Hello", "Hello")
        action_only["turn"]["assistant"]["actions"] = [{
            "tool": "add_activity", "arguments": {"name": "Remember this"},
        }]
        self.assertNotEqual(classify_archive_candidate(action_only)["status"], "protected")

    def test_batch_groups_keep_source_order_and_do_not_mutate_inputs(self):
        candidates = [
            archived_turn("Can you explain queues?", timestamp="2026-01-01T00:01:00+00:00"),
            archived_turn("Remember that I prefer short answers.", timestamp="2026-01-01T00:02:00+00:00"),
            archived_turn("Maybe later.", timestamp="2026-01-01T00:03:00+00:00"),
            archived_turn("We decided to keep the current schema.", timestamp="2026-01-01T00:04:00+00:00"),
            archived_turn("What is a deque?", timestamp="2026-01-01T00:05:00+00:00"),
        ]
        original = deepcopy(candidates)
        result = classify_compaction_candidates(candidates)

        self.assertEqual(result["candidate_count"], 5)
        self.assertEqual(result["protected_count"], 2)
        self.assertEqual(result["compactable_count"], 2)
        self.assertEqual(result["uncertain_count"], 1)
        self.assertEqual(
            [item["archived_turn"]["turn"]["user"] for item in result["protected"]],
            [candidates[1]["turn"]["user"], candidates[3]["turn"]["user"]],
        )
        self.assertEqual(
            [item["archived_turn"]["turn"]["user"] for item in result["compactable"]],
            [candidates[0]["turn"]["user"], candidates[4]["turn"]["user"]],
        )
        self.assertEqual(result["protected"][0]["archived_turn"]["timestamp"],
                         "2026-01-01T00:02:00+00:00")
        result["protected"][0]["archived_turn"]["turn"]["user"] = "changed copy"
        self.assertEqual(candidates, original)

    def test_stage_two_candidates_are_the_only_input_and_archive_is_unchanged(self):
        first_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            archive_file = Path(directory) / "archive.jsonl"
            records = []
            for number in range(1, 102):
                if number == 1:
                    user = "Remember this: keep my study goal."
                elif number == 2:
                    user = "From now on, keep imported sources."
                elif number == 3:
                    user = "Maybe change this later."
                else:
                    user = f"Can you explain queue item {number}?"
                records.append(archived_turn(
                    user,
                    timestamp=(first_time + timedelta(minutes=number)).isoformat(),
                ))
            archive_file.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            original_bytes = archive_file.read_bytes()
            with patch.object(ai_memory, "ARCHIVE_FILE", archive_file), \
                    patch.object(ai_memory, "_sessions", {"test-session": [
                        {"user": "Recent only", "assistant": "Reply"},
                    ]}):
                selection = ai_memory.select_archive_compaction_candidates()
                with patch.object(ai_memory, "_iter_archived_turns",
                                  side_effect=AssertionError("archive reread")):
                    result = classify_compaction_candidates(
                        selection["compaction_candidates"],
                    )
            self.assertEqual(archive_file.read_bytes(), original_bytes)

        self.assertEqual(selection["candidate_count"], 50)
        self.assertEqual(result["candidate_count"], 50)
        self.assertEqual(result["protected_count"], 2)
        self.assertEqual(result["compactable_count"], 47)
        self.assertEqual(result["uncertain_count"], 1)
        self.assertEqual(result["protected"][0]["archived_turn"]["turn"]["user"],
                         records[0]["turn"]["user"])
        self.assertNotIn("Recent only", str(result))

    def test_empty_batch_and_wrong_stage_two_argument(self):
        self.assertEqual(classify_compaction_candidates([])["candidate_count"], 0)
        with self.assertRaisesRegex(ValueError, "compaction_candidates list"):
            classify_compaction_candidates({"compaction_candidates": []})


if __name__ == "__main__":
    unittest.main()
