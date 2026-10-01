"""A few offline safety checks for the standalone debug command."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import memory_debug as debug


class MemoryDebugTests(unittest.TestCase):
    def test_no_llm_run_uses_real_rules_and_restores_production_settings(self):
        archive = debug.memory.ARCHIVE_FILE
        durable = debug.durable.DURABLE_MEMORY_FILE
        threshold = debug.memory.ARCHIVE_TURN_THRESHOLD
        batch = debug.memory.ARCHIVE_COMPACT_BATCH
        with patch.object(debug.classifier, "OpenAI") as client, redirect_stdout(io.StringIO()) as trace:
            result = debug.run_debug()
        client.assert_not_called()
        self.assertEqual(result["initial_fake_turns"], 16)
        self.assertEqual(result["stage_2_candidates"], 14)
        self.assertIn("UNCERTAIN", trace.getvalue())
        self.assertIn("Skipped: LLM disabled", trace.getvalue())
        self.assertEqual(debug.memory.ARCHIVE_FILE, archive)
        self.assertEqual(debug.durable.DURABLE_MEMORY_FILE, durable)
        self.assertEqual(debug.memory.ARCHIVE_TURN_THRESHOLD, threshold)
        self.assertEqual(debug.memory.ARCHIVE_COMPACT_BATCH, batch)

    def test_full_mocked_flow_dry_run_and_optional_fake_writes_are_isolated(self):
        def parse(**kwargs):
            payload = json.loads(kwargs["input"][0]["content"])
            if "uncertain_candidates" in payload:
                value = {"classifications": [
                    {"candidate_index": item["candidate_index"], "status": "compactable",
                     "category": "other_short_term", "reason": "Mock temporary discussion."}
                    for item in payload["uncertain_candidates"]
                ]}
            elif "compactable_turns" in payload:
                value = {name: {"summary": [], "keywords": []}
                         for name in debug.summary.BASE_ARCHIVE_CATEGORIES}
                value["general"] = {"summary": ["Discussed internship applications.", "Discussed CV preparation."],
                                    "keywords": ["internships", "CV"]}
                value.update(needs_category_review=True, uncategorized_item_refs=[0, 1])
            elif "unresolved_general_items" in payload:
                value = {"needs_new_category": True, "proposed_category": "career",
                         "reason": "Two distinct career topics.",
                         "example_topics": ["internships", "CV"], "item_refs": [0, 1]}
            else:
                value = {"memories": [
                    {"type": "constraint", "content": item["user"], "status": "active",
                     "source_turn_refs": [item["source_turn_ref"]],
                     "source_timestamp": item["timestamp"]}
                    for item in payload["protected_turns"]
                ]}
            return SimpleNamespace(status="completed", output_parsed=value)

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            sentinel_archive = Path(directory) / "real-archive.jsonl"
            sentinel_durable = Path(directory) / "real-durable.json"
            sentinel_archive.write_bytes(b"do not read or change archive")
            sentinel_durable.write_bytes(b"do not read or change durable")
            stack.enter_context(patch.object(debug.memory, "ARCHIVE_FILE", sentinel_archive))
            stack.enter_context(patch.object(debug.durable, "DURABLE_MEMORY_FILE", sentinel_durable))
            stack.enter_context(patch.dict(debug.durable.os.environ, {"OPENAI_API_KEY": "offline-test-key"}))
            for module in (debug.classifier, debug.summary, debug.review, debug.durable):
                stack.enter_context(patch.object(module, "is_openai_api_key_configured", return_value=True))
                mock = stack.enter_context(patch.object(module, "OpenAI"))
                mock.return_value.__enter__.return_value.responses.parse.side_effect = parse
            for write_fake in (False, True):
                with self.subTest(write_fake=write_fake), redirect_stdout(io.StringIO()) as trace:
                    result = debug.run_debug(llm=True, write_fake=write_fake)
                self.assertEqual(result["stage_4_5"], "accepted")
                self.assertGreater(result["would_remove_raw_turns"], 0)
                self.assertGreater(result["durable_memories_extracted"], 0)
                self.assertIn("career", trace.getvalue())
                self.assertEqual(sentinel_archive.read_bytes(), b"do not read or change archive")
                self.assertEqual(sentinel_durable.read_bytes(), b"do not read or change durable")

    def test_individual_stage_does_not_call_unneeded_downstream_functions(self):
        with patch.object(debug.classifier, "classify_uncertain_archive_candidates") as classify, \
                patch.object(debug.summary, "summarize_compactable_archive_turns") as summarize, \
                redirect_stdout(io.StringIO()):
            debug.run_debug(stage="2.5", llm=True)
        classify.assert_not_called()
        summarize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
