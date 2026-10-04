import sqlite3
import unittest
from backend.app.conversations import storage
from backend.app.ai.context.adaptive import store

EMPTY = {"activities_scope": None, "include_exams": False, "exam_scope": None}


def make_event(owner, chat, request="request-1", **changes):
    return {"event_id": chat + request, "owner_id": owner, "conversation_id": chat,
            "request_id": request, "timestamp": "2026-10-04T09:00:00+00:00",
            "classifier_model": "test-model", "classifier_version": "test-v1",
            "pattern": "tell me something", "request_excerpt": "Tell me something",
            "candidates": [], "initial_selection": EMPTY, "final_selection": EMPTY,
            "initial_status": {}, "final_status": {}, **changes}


class AdaptiveStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA foreign_keys=ON")
        storage.migrate(self.connection)
        store.migrate(self.connection)
        self.a = storage.create_conversation(self.connection, "owner-a")["conversation_id"]
        self.other = storage.create_conversation(self.connection, "owner-a")["conversation_id"]
        self.b = storage.create_conversation(self.connection, "owner-b")["conversation_id"]

    def test_retries_are_idempotent_and_ownership_is_required(self):
        event = make_event("owner-a", self.a)
        self.assertTrue(store.record_event(self.connection, event))
        self.assertFalse(store.record_event(self.connection, event))
        self.assertEqual(len(store.load_eligible_evidence(self.connection, "owner-a", self.a)), 1)
        with self.assertRaises(ValueError):
            store.record_event(self.connection, make_event("owner-b", self.a))
        with self.assertRaises(ValueError):
            store.record_label(self.connection, "owner-b", event["event_id"], {
                "signal": "developer", "status": "rejected", "selection": EMPTY})

    def test_sharing_is_rechecked_and_never_crosses_owners(self):
        store.record_event(self.connection, make_event("owner-a", self.a))
        store.record_event(self.connection, make_event("owner-b", self.b))
        self.assertEqual(store.load_eligible_evidence(self.connection, "owner-a", self.other), [])
        storage.set_memory_sharing(self.connection, self.a, "owner-a", True)
        self.assertEqual(len(store.load_eligible_evidence(self.connection, "owner-a", self.other)), 1)
        storage.set_memory_sharing(self.connection, self.a, "owner-a", False)
        self.assertEqual(store.load_eligible_evidence(self.connection, "owner-a", self.other), [])

    def test_latest_label_supersedes_and_reset_preserves_conversations(self):
        event = make_event("owner-a", self.a)
        store.record_event(self.connection, event)
        for status in ("pending", "rejected"):
            store.record_label(self.connection, "owner-a", event["event_id"], {
                "signal": "developer", "status": status, "selection": EMPTY})
        self.assertEqual(store.load_eligible_evidence(self.connection, "owner-a", self.a)[0]["label"].status, "rejected")
        store.reset_owner_learning(self.connection, "owner-a")
        self.assertEqual(store.load_eligible_evidence(self.connection, "owner-a", self.a), [])
        self.assertEqual(len(storage.list_conversations(self.connection, "owner-a")), 2)

    def test_private_urls_and_keys_are_redacted(self):
        event = make_event("owner-a", self.a, request_excerpt="https://private.example/feed.ics sk-abcdefghijklmnopqrstuv")
        store.record_event(self.connection, event)
        clean = store.event_by_id(self.connection, "owner-a", event["event_id"])
        self.assertNotIn("private.example", clean.request_excerpt)
        self.assertNotIn("sk-", clean.request_excerpt)
