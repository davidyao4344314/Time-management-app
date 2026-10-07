"""Stale review cards must never authorize a different activity state."""
import sqlite3
import unittest
from contextlib import closing

from backend.app import database
from backend.app.ai.actions.activity_tool import create_activity_tool_registry, describe_activity_proposals
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ApprovalDecision
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.routing import prepare_tool_proposals
from backend.app.planner.activities import add_activity, get_activity_by_id


class ReviewSnapshotTests(unittest.TestCase):
    def test_same_name_changed_recurrence_refuses_edit_and_delete(self):
        for tool in ("edit_activity", "delete_activity"):
            with self.subTest(tool=tool), closing(sqlite3.connect(":memory:")) as connection:
                database.create_tables(connection)
                identifier = add_activity(connection,
                    ["name", "category", "activity_type", "date"],
                    ["Study", "Study", "one_time", "2026-10-07"])
                arguments = {"activity_id": identifier, "expected_name": "Study"}
                if tool == "edit_activity":
                    arguments["changes"] = [{"column_name": "subject", "new_value": "Maths"}]
                proposals = prepare_tool_proposals([{"tool": tool, "arguments": arguments}], create_proposal_tool_registry())
                proposal = describe_activity_proposals(connection, proposals)[0]
                connection.execute("UPDATE activities SET activity_type='daily', date=NULL WHERE id=?", (identifier,))
                connection.commit()
                approval = ApprovalBoundary()
                approval.register(proposal)
                approval.decide(proposal.id, ApprovalDecision.APPROVE)
                result = ActionExecutor(create_activity_tool_registry(connection), approval).execute(proposal.id)
                self.assertFalse(result.success)
                self.assertIn("changed since review", result.error)
                self.assertEqual(get_activity_by_id(connection, identifier)[4], "daily")
