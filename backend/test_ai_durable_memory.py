"""Offline Stage 6 tests plus optional A-I demonstrations in temporary storage.

--examples uses mocked model responses and costs nothing.
--live makes paid OpenAI requests; it still never touches the real archive/store.
"""

import json
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import ai_durable_memory as durable, ai_memory
from backend.app.ai_archive_protection import classify_compaction_candidates
from backend.app.ai_archive_llm_classifier import classify_uncertain_archive_candidates


MANUAL_CASES = (
    ("A", "Remember this: always ask before changing activities.",
     [("explicit_memory", "Always ask for user approval before changing activities.")]),
    ("B", "My long-term goal is to finish the app before semester ends.",
     [("goal", "Finish the app before semester ends.")]),
    ("C", "I prefer one meaningful Git commit per feature.",
     [("preference", "Use one meaningful Git commit per feature.")]),
    ("D", "We decided archive retrieval should search only when needed.",
     [("decision", "Search archived memory only when needed.")]),
    ("E", "The LLM must never execute SQL directly.",
     [("constraint", "The LLM must never execute SQL directly.")]),
    ("F", "Maybe I'll study Python tonight.", []),
    ("G", "Why is this loop broken?", []),
    ("H", "My long-term goal is to finish the app before semester ends. "
     "I prefer one meaningful Git commit per feature.",
     [("goal", "Finish the app before semester ends."),
      ("preference", "Use one meaningful Git commit per feature.")]),
    ("I", "User approval is required before executing agent actions.",
     [("constraint", "User approval is required before executing agent actions.")]),
)


def protected(user, *, session="test-session", timestamp="2026-09-30T10:00:00+00:00",
              assistant="Understood; no action has been executed.", with_id=True):
    record = {"session_id": session, "turn": {
        "user": user, "assistant": {"message": assistant, "actions": []},
    }}
    if with_id:
        record["turn_id"] = str(uuid.uuid4())
    if timestamp is not None:
        record["timestamp"] = timestamp
    return {"status": "protected", "archived_turn": record}


def model_memory(entry, memory_type="constraint", content="Always require user approval."):
    record = entry["archived_turn"]
    identity = durable._source_identity(record)
    return {"type": memory_type, "content": content, "status": "active",
            "source_turn_refs": [identity["turn_id"] or "legacy:" + identity["record_sha256"]],
            "source_timestamp": durable._source_timestamp(record)}


class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "durable.json"
        patches = (
            patch.object(durable, "DURABLE_MEMORY_FILE", self.path),
            patch.object(durable, "is_openai_api_key_configured", return_value=True),
            patch.dict(durable.os.environ, {"OPENAI_API_KEY": "offline-test-key"}),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        client_patch = patch.object(durable, "OpenAI")
        self.openai = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client = self.openai.return_value.__enter__.return_value

    def response(self, memories, *, status="completed"):
        self.client.responses.parse.return_value = SimpleNamespace(
            status=status, output_parsed={"memories": memories},
        )

    def read_memories(self):
        return json.loads(self.path.read_bytes())["durable_memories"]

    def seed(self, entry=None, content="Agent actions require user approval before execution."):
        entry = entry or protected(content)
        self.response([model_memory(entry, content=content)])
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "success")
        return entry

    def test_a_to_h_schema_examples_and_multiple_memories(self):
        for label, user, expected in MANUAL_CASES[:8]:
            with self.subTest(case=label):
                entry = protected(user)
                self.response([model_memory(entry, kind, content) for kind, content in expected])
                result = durable.extract_durable_memories([entry])
                self.assertEqual(result["memories_extracted"], len(expected))
                self.assertEqual(result["status"], "success" if expected else "nothing_to_extract")
        saved = self.read_memories()
        self.assertEqual(len(saved), 5)  # H reuses the B/C facts with extra sources.
        self.assertEqual(len(saved[1]["source_turn_refs"]), 2)
        self.assertEqual(len(saved[2]["source_turn_refs"]), 2)

    def test_i_active_passive_duplicate_reuses_id_and_merges_sources(self):
        first = self.seed()
        existing = self.read_memories()[0]
        second = protected("User approval is required before executing agent actions.")
        self.response([model_memory(second, content=second["archived_turn"]["turn"]["user"])])
        result = durable.extract_durable_memories([second])
        self.assertEqual(result, {"status": "success", "input_protected_turns": 1,
                                 "memories_extracted": 1, "memories_created": 0,
                                 "duplicates_reused": 1})
        saved = self.read_memories()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["memory_id"], existing["memory_id"])
        self.assertEqual(saved[0]["created_at"], existing["created_at"])
        self.assertEqual(saved[0]["content"], existing["content"])
        self.assertEqual([ref["turn_id"] for ref in saved[0]["source_turn_refs"]],
                         [first["archived_turn"]["turn_id"], second["archived_turn"]["turn_id"]])

    def test_stage_2_5_and_stage_3_protected_entries_are_accepted(self):
        raw = protected("Remember this: always ask before changing activities.")["archived_turn"]
        stage_2_5 = classify_compaction_candidates([raw])
        uncertain = classify_compaction_candidates([
            protected("I prefer one meaningful Git commit per feature.")["archived_turn"],
        ])["uncertain"]
        with patch("backend.app.ai_archive_llm_classifier.is_openai_api_key_configured",
                   return_value=False):
            stage_3 = classify_uncertain_archive_candidates(uncertain)
        final = stage_2_5["protected"] + stage_3["protected"]
        self.response([model_memory(final[0]), model_memory(final[1], "preference", "One commit per feature.")])
        self.assertEqual(durable.extract_durable_memories(final)["memories_created"], 2)

    def test_only_minimal_protected_text_is_sent_and_input_is_unchanged(self):
        entry = protected("Remember this: always ask before changing activities.")
        original = deepcopy(entry)
        self.response([model_memory(entry)])
        result = durable.extract_durable_memories([entry])
        self.assertEqual(result["status"], "success")
        self.assertEqual(entry, original)
        call = self.client.responses.parse.call_args.kwargs
        payload = json.loads(call["input"][0]["content"])
        self.assertEqual(list(payload), ["protected_turns"])
        self.assertEqual(set(payload["protected_turns"][0]),
                         {"source_turn_ref", "timestamp", "user", "assistant"})
        self.assertNotIn("actions", payload["protected_turns"][0])
        self.assertEqual(call["instructions"], durable.DURABLE_MEMORY_INSTRUCTIONS)
        self.assertEqual(call["text_format"], durable.DurableMemoryExtraction)
        self.assertFalse(call["store"])
        self.assertEqual(call["reasoning"], {"effort": "none"})

    def test_empty_input_and_no_memories_do_not_create_storage(self):
        self.assertEqual(durable.extract_durable_memories([])["status"], "nothing_to_extract")
        self.openai.assert_not_called()
        self.response([])
        result = durable.extract_durable_memories([protected("Maybe I'll study Python tonight.")])
        self.assertEqual(result["status"], "nothing_to_extract")
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_name(self.path.name + ".lock").exists())

    def test_nonprotected_summaries_recent_turns_and_invalid_inputs_are_rejected(self):
        entry = protected("A rule")
        bad_inputs = (
            {"protected": [entry]}, [{**entry, "status": "compactable"}],
            [{**entry, "status": "uncertain"}], [entry["archived_turn"]],
            [{"user": "recent turn", "assistant": "reply"}],
            [{"status": "protected", "archived_turn": {"record_type": "compressed_summary", "turn": {}}}],
            [entry, entry], [{"status": "protected", "archived_turn": {"turn": {"user": "A rule"}}}],
        )
        for entries in bad_inputs:
            with self.subTest(entries=entries):
                self.assertEqual(durable.extract_durable_memories(entries)["status"], "failed")
        self.openai.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_all_invalid_outputs_leave_existing_memory_unchanged(self):
        self.seed()
        before = self.path.read_bytes()
        entry = protected("Remember this rule")
        good = model_memory(entry)
        bad_memories = (
            {**good, "type": "made_up_type"}, {**good, "content": " "},
            {**good, "content": "x" * 321}, {**good, "content": "one\ntwo"},
            {**good, "status": "inactive"}, {**good, "unknown": True},
            {**good, "source_turn_refs": []}, {**good, "source_turn_refs": ["invented"]},
            {**good, "source_turn_refs": [True]},
            {**good, "source_turn_refs": good["source_turn_refs"] * 2},
            {**good, "source_timestamp": "2000-01-01T00:00:00Z"},
            {key: value for key, value in good.items() if key != "status"},
        )
        for invalid in bad_memories:
            with self.subTest(invalid=invalid):
                self.response([good, invalid])
                self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
                self.assertEqual(self.path.read_bytes(), before)
        self.client.responses.parse.return_value.output_parsed = {"memories": "not a list"}
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.client.responses.parse.return_value.output_parsed = {"memories": [], "advice": "unknown field"}
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")

    def test_multiple_source_refs_and_legacy_timestamps_are_preserved(self):
        first = protected("Remember the rule", with_id=False, timestamp=None)
        first["archived_turn"]["turn"]["timestamp"] = "2026-09-29T11:00:00+12:00"
        second = protected("The same rule", timestamp=None)
        memory = model_memory(first)
        memory["source_turn_refs"] += model_memory(second)["source_turn_refs"]
        self.response([memory])
        self.assertEqual(durable.extract_durable_memories([first, second])["status"], "success")
        saved = self.read_memories()[0]
        self.assertIsNone(saved["source_turn_refs"][0]["turn_id"])
        self.assertEqual(saved["source_turn_refs"][0]["record_sha256"],
                         durable._source_identity(first["archived_turn"])["record_sha256"])
        self.assertEqual(saved["source_timestamp"], "2026-09-29T11:00:00+12:00")
        self.assertIsNone(saved["source_turn_refs"][1]["timestamp"])
        self.assertEqual(len(saved["source_turn_refs"]), 2)

    def test_date_is_not_invented_for_undated_legacy_turn(self):
        entry = protected("Remember the rule", with_id=False, timestamp=None)
        self.response([model_memory(entry)])
        durable.extract_durable_memories([entry])
        self.assertIsNone(self.read_memories()[0]["source_timestamp"])

    def test_normalization_preserves_negations_numbers_order_and_types(self):
        originals = (
            "Use 5 recent turns.", "Use 50 recent turns.",
            "Allow agent actions.", "Do not allow agent actions.",
            "Study before dinner.", "Dinner before study.",
        )
        self.assertEqual(len({durable._normalized_content(text) for text in originals}), 6)
        self.assertEqual(durable._normalized_content("  USE five turns! "),
                         durable._normalized_content("Use five turns."))
        self.assertNotEqual(durable._normalized_content("Use 1.5 hours."),
                            durable._normalized_content("Use 1/5 hours."))
        entry = protected("A goal and a preference")
        self.response([model_memory(entry, "goal", "Finish the app."),
                       model_memory(entry, "preference", "Finish the app.")])
        self.assertEqual(durable.extract_durable_memories([entry])["memories_created"], 2)

    def test_sessions_are_separate_and_small_batches_are_all_or_nothing(self):
        first = protected("A persistent rule", session="one")
        second = protected("A persistent rule", session="two")
        self.client.responses.parse.side_effect = [
            SimpleNamespace(status="completed", output_parsed={"memories": [model_memory(first)]}),
            SimpleNamespace(status="completed", output_parsed={"memories": [model_memory(second)]}),
        ]
        self.assertEqual(durable.extract_durable_memories([first, second])["memories_created"], 2)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        before = self.path.read_bytes()
        self.client.responses.parse.side_effect = [
            SimpleNamespace(status="completed", output_parsed={"memories": [model_memory(first)]}),
            TimeoutError("API key must not appear in error"),
        ]
        with patch.object(durable, "DURABLE_MEMORY_BATCH_SIZE", 1):
            result = durable.extract_durable_memories([first, second])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.path.read_bytes(), before)

    def test_api_missing_key_incomplete_and_refusal_fail_safely(self):
        entry = protected("A durable rule")
        durable.is_openai_api_key_configured.return_value = False
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.openai.assert_not_called()
        durable.is_openai_api_key_configured.return_value = True
        self.client.responses.parse.side_effect = TimeoutError("secret-value")
        result = durable.extract_durable_memories([entry])
        self.assertNotIn("secret-value", str(result))
        self.client.responses.parse.side_effect = None
        self.response([], status="incomplete")
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.client.responses.parse.return_value.output_parsed = None
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.assertFalse(self.path.exists())

    def test_api_key_is_redacted_on_input_and_rejected_in_extracted_content(self):
        key = "sk-" + "secret" * 5
        entry = protected("Remember this rule. " + key)
        self.response([model_memory(entry, content="Store key " + key)])
        result = durable.extract_durable_memories([entry])
        self.assertEqual(result["status"], "failed")
        self.assertNotIn(key, str(result))
        self.assertNotIn(key, self.client.responses.parse.call_args.kwargs["input"][0]["content"])
        self.assertFalse(self.path.exists())

    def test_raw_archive_is_never_read_or_modified(self):
        raw = Path(self.directory.name) / "archive.jsonl"
        raw.write_bytes(b"raw protected conversation\n")
        before = raw.read_bytes()
        entry = protected("Remember this rule")
        self.response([model_memory(entry)])
        with patch.object(ai_memory, "ARCHIVE_FILE", raw), \
                patch.object(ai_memory, "_iter_archived_turns", side_effect=AssertionError("archive read")):
            self.assertEqual(durable.extract_durable_memories([entry])["status"], "success")
        self.assertEqual(raw.read_bytes(), before)

    def test_write_replace_and_verification_failures_preserve_old_store(self):
        self.seed()
        before = self.path.read_bytes()
        entry = protected("A different goal")
        self.response([model_memory(entry, "goal", "Finish the planner.")])
        for target in ("_write_verified_temp", "os.replace"):
            with self.subTest(target=target):
                patcher = patch("backend.app.ai_durable_memory." + target,
                                side_effect=OSError("disk-full-secret"))
                with patcher:
                    result = durable.extract_durable_memories([entry])
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("disk-full-secret", str(result))
                self.assertEqual(self.path.read_bytes(), before)
        real_fsync = durable._fsync_directory
        calls = 0

        def fail_once_after_replace(directory):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("post-replace failure")
            return real_fsync(directory)

        with patch.object(durable, "_fsync_directory", side_effect=fail_once_after_replace):
            self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_first_creation_leaves_no_memory_file(self):
        entry = protected("A goal")
        self.response([model_memory(entry, "goal", "Finish the planner.")])
        with patch.object(durable, "_fsync_directory", side_effect=OSError("fsync failed")):
            self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.assertFalse(self.path.exists())

    def test_corrupted_or_symlink_store_is_not_overwritten(self):
        entry = protected("A goal")
        self.response([model_memory(entry, "goal", "Finish the planner.")])
        self.path.write_bytes(b"invalid-json")
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.assertEqual(self.path.read_bytes(), b"invalid-json")
        self.path.unlink()
        other = Path(self.directory.name) / "unrelated.txt"
        other.write_bytes(b"untouched")
        self.path.symlink_to(other)
        self.assertEqual(durable.extract_durable_memories([entry])["status"], "failed")
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(other.read_bytes(), b"untouched")

    def test_retry_is_idempotent_and_files_are_private(self):
        entry = self.seed()
        before = self.path.read_bytes()
        result = durable.extract_durable_memories([entry])
        self.assertEqual(result["memories_created"], 0)
        self.assertEqual(result["duplicates_reused"], 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        lock = self.path.with_name(self.path.name + ".lock")
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)

    def test_concurrent_writers_do_not_lose_memories(self):
        entries = [protected("First goal"), protected("Second goal")]
        extracted = [durable._resolve_extraction({"memories": [model_memory(entry, "goal", name)]},
                                                 durable._protected_sources([entry]))
                     for entry, name in zip(entries, ("Finish app.", "Learn Python."))]

        def save(memories):
            with durable._durable_write_lock():
                return durable._persist_memories(memories)

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(save, extracted)), [(1, 0), (1, 0)])
        self.assertEqual(len(self.read_memories()), 2)
        backup = self.path.with_name("durable.backup.json")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)


def demonstrate_cases(*, live=False):
    """A-I examples use disposable storage, never the user's live memory file."""
    print("PAID live model test" if live else "OFFLINE examples: model responses are mocked")
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(durable, "DURABLE_MEMORY_FILE", Path(directory) / "demo.json"):
        def run(entry, expected):
            if live:
                return durable.extract_durable_memories([entry])
            with patch.object(durable, "is_openai_api_key_configured", return_value=True), \
                    patch.dict(durable.os.environ, {"OPENAI_API_KEY": "offline-key"}), \
                    patch.object(durable, "OpenAI") as mock:
                mock.return_value.__enter__.return_value.responses.parse.return_value = SimpleNamespace(
                    status="completed", output_parsed={"memories": [
                        model_memory(entry, kind, content) for kind, content in expected
                    ]},
                )
                return durable.extract_durable_memories([entry])

        for label, user, expected in MANUAL_CASES:
            if label == "I":
                seed = protected("Agent actions require user approval before execution.")
                seed_result = run(seed, [("constraint", seed["archived_turn"]["turn"]["user"])])
                if seed_result["status"] != "success":
                    print(json.dumps(seed_result, indent=2))
                    return
            print(f"\nCase {label}: {user}")
            result = run(protected(user), expected)
            print(json.dumps(result, indent=2))
            if result["status"] == "failed":
                return
        if durable.DURABLE_MEMORY_FILE.exists():
            print("\nStored structure (temporary examples only):")
            print(json.dumps(json.loads(durable.DURABLE_MEMORY_FILE.read_bytes()), indent=2))
    print("Temporary sample storage removed; real archive and durable memory unchanged.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in {"--examples", "--live"}:
        demonstrate_cases(live=sys.argv[1] == "--live")
    else:
        unittest.main()
