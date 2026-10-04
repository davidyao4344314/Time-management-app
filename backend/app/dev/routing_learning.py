"""Review local routing evidence. No LLM calls; explicit owner scope required."""

import argparse
import json
import sqlite3
from pathlib import Path

from backend.app import database
from backend.app.ai.context.adaptive import store
from backend.app.ai.context.adaptive.learning import apply_reviewed_label, approve_pattern
from backend.app.ai.context.adaptive.patterns import compile_patterns


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=database.db_file)
    parser.add_argument("--owner", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--chat", required=True)
    patterns = commands.add_parser("patterns")
    patterns.add_argument("--chat", required=True)
    activation = commands.add_parser("activate")
    activation.add_argument("--chat", required=True)
    activation.add_argument("--pattern", required=True)
    activation.add_argument("--confirm-shadow-review", action="store_true")
    review = commands.add_parser("label")
    review.add_argument("--event", required=True)
    review.add_argument("--selection", required=True, help="Existing ContextSelection JSON.")
    review.add_argument("--fields", required=True, help="Comma-separated fields explicitly confirmed.")
    review.add_argument("--classification", help="Reviewed AgentRoutingDecision JSON for an example.")
    review.add_argument("--approve-example", action="store_true")
    reject = commands.add_parser("reject")
    reject.add_argument("--event", required=True)
    reset = commands.add_parser("reset")
    reset.add_argument("--confirm-reset", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "reset" and not args.confirm_reset:
        parser.error("Reset requires --confirm-reset and affects only this owner's learning.")
    try:
        # mode=rw refuses a missing database; it never creates a new app database.
        with sqlite3.connect(args.database.resolve().as_uri() + "?mode=rw", uri=True) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            if args.command == "list":
                records = store.load_eligible_evidence(connection, args.owner, args.chat, limit=20)
                result = [{"event_id": item["event"].event_id,
                           "request": item["event"].request_excerpt,
                           "selection": item["event"].initial_selection.model_dump(),
                           "recovered": item["event"].recovery_requested,
                           "label": item["label"].model_dump() if item["label"] else None} for item in records]
            elif args.command == "reset":
                store.reset_owner_learning(connection, args.owner)
                result = {"reset": True}
            elif args.command == "patterns":
                result = compile_patterns(store.load_eligible_evidence(connection, args.owner, args.chat),
                                          states=store.load_pattern_states(connection, args.owner, args.chat))
            elif args.command == "activate":
                approve_pattern(connection, args.owner, args.chat, args.pattern, shadow_reviewed=args.confirm_shadow_review)
                result = {"approved": True}
            else:
                if args.command == "reject":
                    event = store.event_by_id(connection, args.owner, args.event)
                    label = {"signal": "developer", "status": "rejected", "selection": event.final_selection.model_dump()}
                else:
                    label = {"signal": "developer", "status": "confirmed", "selection": json.loads(args.selection),
                             "confirmed_fields": args.fields.split(","), "example_approved": args.approve_example,
                             "classification": json.loads(args.classification) if args.classification else None}
                result = {"label_id": apply_reviewed_label(connection, args.owner, args.event, label)}
        print(json.dumps(result, indent=2))
        return 0
    except (sqlite3.Error, OSError, ValueError):
        print(json.dumps({"error": "Could not access or validate scoped routing evidence. Check IDs, JSON and database."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
