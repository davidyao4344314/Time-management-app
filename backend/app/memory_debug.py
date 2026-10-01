"""Standalone fake-data memory trace. Nothing imports this in production.

Default: no model calls, no persistence. --llm opts into paid calls; --write-fake
opts into writing disposable fake files. Never run this inside the API process:
the temporary module patches are confined to this standalone CLI's process.
"""

import argparse
import json
import tempfile
import uuid
from contextlib import ExitStack, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import (
    ai_memory as memory, ai_archive_protection as protection,
    ai_archive_llm_classifier as classifier, ai_archive_summary as summary,
    ai_archive_category_review as review, ai_archive_persistence as persistence,
    ai_durable_memory as durable,
)


from backend.app.memory.compaction_plan import preview_compacted_archive


DEBUG_ARCHIVE_THRESHOLD = 10
DEBUG_COMPACT_BATCH = 14
FAKE_TURNS = (
    ("What am I doing tomorrow?", "You have a tutorial from 2 PM to 3 PM."),
    ("What tests do I have next week?", "The example COMPSCI test is next week."),
    ("How does numbers[1:] work in recursion?", "It returns the rest of the list."),
    ("Why is my FastAPI server failing?", "Uvicorn was missing from the virtual environment."),
    ("Remember this: agent actions must require my approval.", "Understood; nothing was executed."),
    ("My long-term goal is to finish the study planner before semester ends.", "Understood."),
    ("From now on I prefer one meaningful Git commit per feature.", "Understood."),
    ("We decided recurrence logic should stay in Python.", "React displays resolved dates."),
    ("Maybe I should keep working on the memory system later.", "That is a tentative idea."),
    ("What is involved in internship applications?", "Discussed internships and CV preparation."),
    ("How do I prepare a CV for internships?", "Discussed CV sections and interview preparation."),
    ("Thanks, that worked.", "Glad the temporary issue is resolved."),
    ("Do not change activities without user approval.", "The approval constraint remains in place."),
    ("Can you explain recursive list slicing again?", "numbers[1:] returns the rest of the list."),
    ("What is on my calendar on Friday?", "A sample lecture; this newer turn stays unselected."),
    ("How do I restart Vite?", "Run npm run dev; this newer turn stays unselected."),
)


def fake_archive():
    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [{
        "turn_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"memory-debug/turn_{index:03d}")),
        "session_id": "fake-debug-session",
        "timestamp": (first + timedelta(hours=index)).isoformat(),
        "turn": {"user": user, "assistant": {"message": assistant, "actions": []}},
    } for index, (user, assistant) in enumerate(FAKE_TURNS, 1)]


def section(title):
    print("\n" + "=" * 60 + "\n" + title + "\n" + "=" * 60)


def show(value):
    # Debug output has fake data only; still use the existing secret redactor.
    print(json.dumps(memory._redact_secrets(value), indent=2, ensure_ascii=False))


def _stage5_preview(final, entries, records):
    """Reuse the pure production preview without persistence."""
    return preview_compacted_archive(
        final, entries, records,
        summary_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "memory-debug/summary")),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def run_debug(*, stage="all", llm=False, write_fake=False):
    if stage not in {"all", "1", "2", "2.5", "3", "4", "4.5", "5", "6"}:
        raise ValueError("Choose an existing memory stage.")
    records = fake_archive()
    labels = {record["turn_id"]: f"turn_{index:03d}" for index, record in enumerate(records, 1)}

    def ids(rows):
        return [labels[row["turn_id"]] for row in rows]

    stats = {"initial_fake_turns": len(records), "llm_enabled": llm,
             "dry_run": not write_fake, "stage_2_candidates": 0,
             "final_protected": 0, "final_compactable": 0, "unresolved_uncertain": 0,
             "stage_4_nonempty_categories": 0, "stage_4_5": "not_run",
             "would_remove_raw_turns": 0, "durable_memories_extracted": 0,
             "real_archive_modified": "NO", "real_durable_memory_modified": "NO"}
    section("INITIAL FAKE ARCHIVE")
    print("LLM: " + ("ENABLED — paid requests" if llm else "DISABLED — no model calls"))
    print("Persistence: " + ("disposable fake files only" if write_fake else "DRY RUN"))
    for record in records:
        print(f"\n{labels[record['turn_id']]} | {record['turn_id']} | {record['timestamp']}")
        print("User: " + record["turn"]["user"])
        print("Assistant: " + record["turn"]["assistant"]["message"])

    # Every storage path is redirected BEFORE a production function is called.
    # No production archive is read to construct this fixture.
    with tempfile.TemporaryDirectory(prefix="memory-debug-") as directory, ExitStack() as stack:
        archive = Path(directory) / "fake_archive.jsonl"
        store = Path(directory) / "fake_durable.json"
        archive.write_bytes(b"".join(persistence._canonical_bytes(row) + b"\n" for row in records))
        initial = archive.read_bytes()
        stack.enter_context(patch.object(memory, "ARCHIVE_FILE", archive))
        stack.enter_context(patch.object(memory, "ARCHIVE_TURN_THRESHOLD", DEBUG_ARCHIVE_THRESHOLD))
        stack.enter_context(patch.object(memory, "ARCHIVE_COMPACT_BATCH", DEBUG_COMPACT_BATCH))
        stack.enter_context(patch.object(durable, "DURABLE_MEMORY_FILE", store))
        try:
            section("STAGE 1 — THRESHOLD CHECK")
            count = memory.get_archive_turn_count()
            show({"archive_count": count, "debug_threshold": DEBUG_ARCHIVE_THRESHOLD,
                  "needs_compaction": memory.archive_needs_compaction(count)})
            if stage == "1":
                return stats

            section("STAGE 2 — CANDIDATE SELECTION")
            selection = memory.select_archive_compaction_candidates()
            candidates = selection["compaction_candidates"]
            stats["stage_2_candidates"] = len(candidates)
            selected_ids = {row["turn_id"] for row in candidates}
            show({"candidate_count": len(candidates), "selected": ids(candidates),
                  "remaining_untouched": ids([row for row in records if row["turn_id"] not in selected_ids])})
            if stage == "2":
                return stats

            section("STAGE 2.5 — PYTHON PROTECTION RULES")
            groups = protection.classify_compaction_candidates(candidates)
            for status in ("protected", "compactable", "uncertain"):
                print(status.upper() + ":")
                show([{ "turn": labels[entry["archived_turn"]["turn_id"]],
                        "category": entry["category"], "matched_rule": entry["matched_rule"]}
                      for entry in groups[status]])
            final_entries = groups["protected"] + groups["compactable"] + groups["uncertain"]
            if stage == "2.5":
                return stats

            section("STAGE 3 — LLM IMPORTANCE CLASSIFIER")
            uncertain = groups["uncertain"]
            print("ONLY UNCERTAIN INPUT CANDIDATES:")
            show(ids([entry["archived_turn"] for entry in uncertain]))
            show([classifier._minimal_candidate(entry, index) for index, entry in enumerate(uncertain)])
            if llm:
                resolved = classifier.classify_uncertain_archive_candidates(uncertain)
                final_entries = groups["protected"] + groups["compactable"] + resolved["protected"] + resolved["compactable"]
                show([{ "turn": labels[entry["archived_turn"]["turn_id"]],
                        "status": entry["status"], "category": entry["category"], "reason": entry["reason"]}
                      for entry in resolved["protected"] + resolved["compactable"]])
            else:
                print("Skipped: LLM disabled. Uncertain turns remain unresolved; no classifications invented.")
            if stage == "3":
                return stats

            final = None
            if stage != "6":
                section("STAGE 4 — CATEGORY SUMMARY")
                compactable = [entry for entry in final_entries if entry["status"] == "compactable"]
                print("CONFIRMED COMPACTABLE INPUT TURN IDS:")
                show(ids([entry["archived_turn"] for entry in compactable]))
                if llm:
                    # Keep the full classified list for source_index provenance;
                    # the real summarizer itself sends only compactable text.
                    final = summary.summarize_compactable_archive_turns(final_entries)
                    show(final)
                    if final.get("success"):
                        stats["stage_4_nonempty_categories"] = sum(bool(value["summary"]) for value in final["categories"].values())
                else:
                    print("Skipped: LLM disabled. No mock summary created.")
                if stage == "4":
                    return stats

                section("STAGE 4.5 — CATEGORY REVIEW")
                if final and final.get("success"):
                    print("needs_category_review = " + str(final["needs_category_review"]))
                    show([{"item_ref": index, "summary": final["categories"]["general"]["summary"][index]}
                          for index in final["uncategorized_item_refs"]])
                    proposal = []
                    validate_name = review._category_rejection

                    def trace_name(name, existing):
                        proposal.append(name)
                        return validate_name(name, existing)

                    with patch.object(review, "_category_rejection", side_effect=trace_name):
                        final = review.review_archive_summary_categories(final)
                    stats["stage_4_5"] = final["status"]
                    show({"llm_proposed_category": proposal[0] if proposal else None,
                          "python_result": final["status"], "category_added": final["category_added"],
                          "reason": final["reason"]})
                    if final["status"] == "not_needed":
                        print("Stage 4.5 skipped/no expansion: existing categories were sufficient.")
                else:
                    print("Skipped: LLM disabled or Stage 4 did not produce a valid summary.")
                if stage == "4.5":
                    return stats

                section("STAGE 5 — " + ("FAKE-FILE PERSISTENCE" if write_fake else "PERSISTENCE DRY RUN"))
                if final:
                    preview = _stage5_preview(final, final_entries, records)
                    show(preview)
                    stats["would_remove_raw_turns"] = len(preview["would_remove"])
                    if write_fake:
                        show(persistence.persist_compacted_archive(final, final_entries))
                    else:
                        print("NO ARCHIVE FILES MODIFIED — DRY RUN")
                else:
                    print("Skipped: no LLM summary available; nothing can be persisted or simulated.")
                print("Protected turns retained:")
                show(ids([entry["archived_turn"] for entry in final_entries if entry["status"] == "protected"]))
                if stage == "5":
                    return stats

            section("STAGE 6 — DURABLE MEMORY EXTRACTION")
            protected = [entry for entry in final_entries if entry["status"] == "protected"]
            print("ONLY PROTECTED INPUT TURN IDS:")
            show(ids([entry["archived_turn"] for entry in protected]))
            if llm:
                in_memory = {"durable_memories": []}

                def save_in_memory(extracted):
                    nonlocal in_memory
                    in_memory, created, reused = durable._merge_memories(in_memory, extracted)
                    return created, reused

                if write_fake:
                    result = durable.extract_durable_memories(protected)
                    saved = json.loads(store.read_bytes()) if store.exists() else in_memory
                else:
                    with patch.object(durable, "_durable_write_lock", return_value=nullcontext()), \
                            patch.object(durable, "_persist_memories", side_effect=save_in_memory):
                        result = durable.extract_durable_memories(protected)
                    saved = in_memory
                show(result)
                show(saved)
                stats["durable_memories_extracted"] = result.get("memories_extracted", 0)
                print("Invalid extraction is rejected as a whole by production validation.")
            else:
                print("Skipped: LLM disabled. No mock durable memories created.")
            return stats
        finally:
            entries = locals().get("final_entries", [])
            stats["final_protected"] = sum(entry["status"] == "protected" for entry in entries)
            stats["final_compactable"] = sum(entry["status"] == "compactable" for entry in entries)
            stats["unresolved_uncertain"] = sum(entry["status"] == "uncertain" for entry in entries)
            if not write_fake and archive.read_bytes() != initial:
                raise RuntimeError("Dry-run invariant failed: fake archive changed.")
            if not write_fake and store.exists():
                raise RuntimeError("Dry-run invariant failed: fake durable file was created.")
            section("FINAL DEBUG SUMMARY")
            show(stats)
            print("Temporary fixture files are discarded on exit. Production settings are restored.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="all", choices=["all", "1", "2", "2.5", "3", "4", "4.5", "5", "6"])
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--llm", action="store_true", help="Opt into real, paid model calls.")
    model.add_argument("--skip-llm", action="store_true", help="No model calls (the default).")
    parser.add_argument("--write-fake", action="store_true", help="Persist only to disposable fake files; default is dry-run.")
    args = parser.parse_args()
    run_debug(stage=args.stage, llm=args.llm, write_fake=args.write_fake)


if __name__ == "__main__":
    main()
