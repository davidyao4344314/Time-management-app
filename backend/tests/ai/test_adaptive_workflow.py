import json
import unittest
from unittest.mock import patch

from backend.app.ai.context.adaptive import learning, patterns, store
from backend.app.ai.context.adaptive.settings import AdaptiveSettings
from backend.app.ai.agent.transparency import build_adaptive_metadata
from backend.app.dev.adaptive_routing_check import evaluate
from backend.tests.ai import test_adaptive_store as fixtures
from backend.tests.ai.test_adaptive_patterns import evidence_rows, NOW


class AdaptiveWorkflowTests(unittest.TestCase):
    setUp = fixtures.AdaptiveStoreTests.setUp

    def seed(self):
        for row in evidence_rows():
            event = row["event"].model_dump()
            event.update(owner_id="owner-a", conversation_id=self.a)
            store.record_event(self.connection, event)
            learning.apply_reviewed_label(self.connection, "owner-a", event["event_id"], row["label"].model_dump())
        return patterns.pattern_id("help me choose a focus")

    def test_promotion_requires_review_and_revoked_sharing_disables_approved_rule(self):
        with patch.object(patterns, "datetime", wraps=patterns.datetime) as clock:
            clock.now.return_value = NOW
            identifier = self.seed()
            fixtures.storage.set_memory_sharing(self.connection, self.a, "owner-a", True)
            with self.assertRaises(ValueError):
                learning.approve_pattern(self.connection, "owner-a", self.other, identifier, shadow_reviewed=False)
            learning.approve_pattern(self.connection, "owner-a", self.other, identifier, shadow_reviewed=True)
            config = AdaptiveSettings(mode="active")
            snapshot = learning.load_snapshot(self.connection, "owner-a", self.other, config)
            self.assertEqual(snapshot["patterns"][0]["state"], "active")
            fixtures.storage.set_memory_sharing(self.connection, self.a, "owner-a", False)
            self.assertEqual(learning.load_snapshot(self.connection, "owner-a", self.other, config)["patterns"], [])
            with self.assertRaises(ValueError):
                learning.load_snapshot(self.connection, "owner-b", self.other, config)

    def test_negative_correction_needs_new_evidence_and_explicit_reapproval(self):
        with patch.object(patterns, "datetime", wraps=patterns.datetime) as clock:
            clock.now.return_value = NOW
            identifier = self.seed()
            learning.approve_pattern(self.connection, "owner-a", self.a, identifier, shadow_reviewed=True)
            first = store.load_eligible_evidence(self.connection, "owner-a", self.a)[0]
            label = first["label"].model_dump()
            label["selection"] = fixtures.EMPTY
            learning.apply_reviewed_label(self.connection, "owner-a", first["event"].event_id, label)
            with self.assertRaises(ValueError):
                learning.approve_pattern(self.connection, "owner-a", self.a, identifier, shadow_reviewed=True)
            self.assertEqual(learning.load_snapshot(self.connection, "owner-a", self.a, AdaptiveSettings(mode="active"))["patterns"][0]["state"], "suspended")

    def test_public_metadata_has_no_private_examples_or_identifiers(self):
        evidence = {"adaptive": {"pattern_id": "private-id", "owner": "private-owner", "request": "private-text",
                    "shortcut_state": "active", "shortcut_used": True, "confirmed_samples": 30,
                    "observed_agreement": 1.0, "examples_used": 2,
                    "calibration": {"status": "accepted", "confirmed_count": 50, "observed_agreement": 0.98}}}
        result = build_adaptive_metadata(evidence, {"mode": "active"})
        self.assertTrue(result["shortcut_used"])
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(build_adaptive_metadata()["mode"], "off")
        self.assertEqual(build_adaptive_metadata({}, {"mode": "active", "knowledge_unavailable": True})["shortcut_state"], "unavailable")

    def test_offline_evaluation_runs_without_network_database_or_secrets(self):
        result = evaluate()
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["cases"]), 7)
        self.assertEqual(result["cases"][0]["runs"][-1]["classifier_calls"], 0)
