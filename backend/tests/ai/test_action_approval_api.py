"""Generic approval HTTP flow with isolated identities and temporary SQLite."""

import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import actions as api
from backend.app.ai.actions.contracts import ActionProposal
from backend.app.ai.actions.service import ActionProposalService
from backend.app.database import create_tables
from backend.app.infrastructure import identity
from backend.app.planner import activity_service


class ActionApprovalAPITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "actions.db"
        with closing(sqlite3.connect(self.path)) as connection:
            create_tables(connection)
        self.addCleanup(patch.stopall)
        patch.object(identity, "IDENTITY_KEY_FILE", Path(directory.name) / "key").start()
        patch.dict(os.environ, {"ACTION_LAYER_DEV_MODE": "1"}).start()
        patch.object(api, "service", ActionProposalService(api._execution_resources)).start()
        self.connect = patch.object(api.common, "create_connection", side_effect=lambda: sqlite3.connect(self.path)).start()
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)
        self.other = TestClient(app)

    def create_proposal(self):
        response = self.client.post("/actions/dev/proposals", json={})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def decide(self, proposal, decision="confirm", client=None):
        return (client or self.client).post(f"/actions/proposals/{proposal['id']}/decision",
                                          json={"decision": decision})

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT * FROM activities").fetchall()

    def test_public_display_is_pending_and_does_not_expose_execution_details(self):
        proposal = self.create_proposal()
        self.assertEqual(set(proposal), {"id", "display_title", "display_description", "status", "requires_approval", "result"})
        self.assertEqual(proposal["status"], "pending_approval")
        self.assertTrue(proposal["requires_approval"])
        self.assertIsNone(proposal["result"])
        self.assertIn("19:00", proposal["display_description"])
        self.assertEqual(self.client.get("/actions/proposals").json()["proposals"], [proposal])
        self.assertEqual(self.client.get(f"/actions/proposals/{proposal['id']}").json(), proposal)
        self.connect.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_confirm_creates_exactly_one_activity_and_returns_action_result(self):
        proposal = self.create_proposal()
        response = self.decide(proposal)
        self.assertEqual(response.status_code, 200)
        view = response.json()
        self.assertEqual(view["status"], "completed")
        self.assertTrue(view["result"]["success"])
        self.assertEqual(set(view["result"]), {"proposal_id", "success", "result", "error", "message"})
        row = self.rows()[0]
        self.assertEqual(row[0], view["result"]["result"]["activity_id"])
        self.assertEqual(row[1], "Study Maths (approval test)")
        self.assertEqual(row[7:9], ("19:00", "20:00"))
        self.assertEqual(row[11:13], ("Manual", None))
        self.assertEqual(self.decide(proposal).status_code, 409)
        self.assertEqual(len(self.rows()), 1)
        self.connect.assert_called_once()
        self.assertEqual(self.client.get(f"/actions/proposals/{proposal['id']}").json(), view)

    def test_cancel_and_later_confirmation_do_not_execute(self):
        proposal = self.create_proposal()
        cancelled = self.decide(proposal, "cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "rejected")
        self.assertIsNone(cancelled.json()["result"])
        self.assertEqual(self.decide(proposal).status_code, 409)
        self.connect.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_client_cannot_tamper_with_confirmed_arguments_or_approval(self):
        proposal = self.create_proposal()
        for extra in ({"arguments": {"start_time": "03:00"}}, {"tool_name": "delete_activity"},
                      {"approved": True}, {"status": "approved"}, {"owner": "other"}):
            with self.subTest(extra=extra):
                response = self.client.post(f"/actions/proposals/{proposal['id']}/decision",
                                            json={"decision": "confirm", **extra})
                self.assertEqual(response.status_code, 422)
        for decision in (True, "approve", "execute", None):
            with self.subTest(decision=decision):
                self.assertEqual(self.decide(proposal, decision).status_code, 422)
        self.connect.assert_not_called()
        self.assertEqual(self.client.get(f"/actions/proposals/{proposal['id']}").json()["status"], "pending_approval")
        self.assertEqual(self.decide(proposal).status_code, 200)
        self.assertEqual(self.rows()[0][7], "19:00")

    def test_unknown_and_other_owner_ids_are_indistinguishable_and_do_not_execute(self):
        proposal = self.create_proposal()
        unknown = self.client.post("/actions/proposals/missing/decision", json={"decision": "confirm"})
        foreign = self.decide(proposal, client=self.other)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(unknown.json(), foreign.json())
        self.assertEqual(self.other.get("/actions/proposals").json()["proposals"], [])
        self.assertEqual(self.other.get(f"/actions/proposals/{proposal['id']}").status_code, 404)
        self.connect.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_forging_an_unsigned_owner_cookie_cannot_claim_proposals(self):
        proposal = self.create_proposal()
        self.other.cookies.set("ai_owner", self.client.cookies.get("ai_owner"))
        self.assertEqual(self.decide(proposal, client=self.other).status_code, 404)
        self.connect.assert_not_called()

    def test_concurrent_confirmations_only_create_once(self):
        proposal = self.create_proposal()
        self.other.cookies.update(self.client.cookies)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: self.decide(proposal, client=client),
                                      (self.client, self.other)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(len(self.rows()), 1)
        self.connect.assert_called_once()

    def test_connection_failure_leaves_pending_and_cancel_remains_available(self):
        proposal = self.create_proposal()
        self.connect.side_effect = sqlite3.OperationalError("private storage details")
        response = self.decide(proposal)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private storage", response.text)
        self.assertEqual(self.client.get(f"/actions/proposals/{proposal['id']}").json()["status"], "pending_approval")
        self.assertEqual(self.decide(proposal, "cancel").json()["status"], "rejected")
        self.assertEqual(self.rows(), [])

    def test_tool_failure_is_terminal_and_result_survives_refresh(self):
        proposal = self.create_proposal()
        with patch.object(activity_service, "get_activity_by_id", side_effect=RuntimeError("private internals")):
            response = self.decide(proposal)
        self.assertEqual(response.status_code, 200)
        view = response.json()
        self.assertEqual(view["status"], "failed")
        self.assertFalse(view["result"]["success"])
        self.assertIn("unconfirmed", view["result"]["message"])
        self.assertNotIn("private internals", response.text)
        self.assertEqual(self.decide(proposal).status_code, 409)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.client.get("/actions/proposals").json()["proposals"], [view])

    def test_dev_source_is_opt_in_and_cannot_accept_client_proposals(self):
        for payload in ({"arguments": {}}, {"approved": True}, {"tool_name": "add_activity"}):
            self.assertEqual(self.client.post("/actions/dev/proposals", json=payload).status_code, 422)
        with patch.dict(os.environ, {"ACTION_LAYER_DEV_MODE": "0"}):
            self.assertEqual(self.client.post("/actions/dev/proposals", json={}).status_code, 404)
            self.assertFalse(self.client.get("/actions/proposals").json()["dev_enabled"])
        self.assertEqual(api.service.list_proposals(self.client.cookies.get("ai_owner")), [])
        self.connect.assert_not_called()

    def test_restart_drops_ephemeral_proposals_without_executing(self):
        proposal = self.create_proposal()
        with patch.object(api, "service", ActionProposalService(api._execution_resources)):
            self.assertEqual(self.decide(proposal).status_code, 404)
            self.assertEqual(self.client.get("/actions/proposals").json()["proposals"], [])
        self.connect.assert_not_called()

    def test_generic_card_payload_is_not_specific_to_add_activity(self):
        self.client.get("/actions/proposals")
        owner = self.client.cookies.get("ai_owner")
        view = api.service.register(owner, ActionProposal(
            tool_name="future_tool", arguments={}, display_title="Another proposed change",
            display_description="Generic display fields only.",
        ))
        response = self.client.get(f"/actions/proposals/{view['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_title"], "Another proposed change")
        self.assertNotIn("tool_name", response.json())
        self.assertEqual(self.decide(view, "cancel").json()["status"], "rejected")
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
