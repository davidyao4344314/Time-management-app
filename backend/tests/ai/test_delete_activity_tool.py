"""Approval-gated deletion using disposable SQLite; no real user data or API calls."""

import sqlite3
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.app.ai.actions.activity_tool import create_activity_tool_registry, describe_activity_proposals
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ActionProposal, ActionStatus, ApprovalDecision, DeleteActivityArguments
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.tools import Tool, ToolPreconditionError, ToolOutcomeUnconfirmedError
from backend.app.database import create_tables
from backend.app.planner import activities, activity_service


class DeleteActivityToolTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA foreign_keys = ON")
        create_tables(self.connection)
        self.first_id = self.add()
        self.second_id = self.add()
        self.approval = ApprovalBoundary()
        self.registry = create_activity_tool_registry(self.connection)
        self.executor = ActionExecutor(self.registry, self.approval)

    def add(self, **changes):
        fields = {"name": "Study", "category": "Study", "subject": "MATHS 102",
                  "activity_type": "one_time", "date": "2026-10-09", "weekday": None,
                  "start_time": None, "end_time": None, **changes}
        return activities.add_activity(self.connection, list(fields), list(fields.values()))

    def proposal(self, **changes):
        return self.approval.register(ActionProposal(
            tool_name="delete_activity", arguments={"activity_id": self.first_id, "expected_name": "Study", **changes},
            display_title="Delete Activity", display_description="Delete the selected activity.",
        ))

    def test_pending_and_cancelled_proposals_cannot_delete(self):
        proposal = self.proposal()
        with patch.object(activity_service, "delete_activity_record") as remove:
            self.assertFalse(self.executor.execute(proposal.id).success)
            self.approval.decide(proposal.id, ApprovalDecision.REJECT)
            self.assertFalse(self.executor.execute(proposal.id).success)
        remove.assert_not_called()
        self.assertEqual(len(activities.get_all_activities(self.connection)), 2)

    def test_confirm_deletes_only_selected_id_using_existing_delete_function(self):
        proposal = self.proposal()
        self.approval.decide(proposal.id, ApprovalDecision.APPROVE)
        with patch.object(activity_service, "delete_activity", wraps=activities.delete_activity) as remove:
            result = self.executor.execute(proposal.id)
        remove.assert_called_once_with(self.connection, self.first_id, commit=False)
        self.assertTrue(result.success)
        self.assertEqual(result.result, {"activity_id": self.first_id, "deleted": True})
        self.assertIsNone(activities.get_activity_by_id(self.connection, self.first_id))
        self.assertIsNotNone(activities.get_activity_by_id(self.connection, self.second_id))
        self.assertFalse(self.connection.in_transaction)
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.COMPLETED)
        self.assertFalse(self.executor.execute(proposal.id).success)

    def test_missing_or_renamed_target_refuses_before_deletion(self):
        for arguments in ({"activity_id": 999}, {"expected_name": "Different name"}):
            with self.subTest(arguments=arguments):
                proposal = self.proposal(**arguments)
                self.approval.decide(proposal.id, ApprovalDecision.APPROVE)
                with patch.object(activity_service, "delete_activity_record") as remove:
                    result = self.executor.execute(proposal.id)
                self.assertFalse(result.success)
                self.assertIn("Request a new proposal", result.error)
                self.assertIn("did not run", result.message)
                remove.assert_not_called()
                self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
        self.assertEqual(len(activities.get_all_activities(self.connection)), 2)

    def test_invalid_or_bulk_arguments_are_rejected_without_deletion(self):
        invalid = [{"activity_id": value, "expected_name": "Study"} for value in (True, 0, -1, "1", None)]
        invalid += [{"activity_id": self.first_id, "expected_name": value} for value in (None, "", " ")]
        invalid += [{"activity_id": self.first_id},
                    {"activity_id": self.first_id, "expected_name": "Study", "approved": True},
                    {"activity_id": [self.first_id, self.second_id], "expected_name": "Study"},
                    {"name": "Study"}]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                DeleteActivityArguments.model_validate(arguments)
        self.assertEqual(len(activities.get_all_activities(self.connection)), 2)

    def test_delete_public_schema_has_no_handler_or_preflight(self):
        tool = create_proposal_tool_registry().resolve("delete_activity")
        self.assertIsNone(tool.handler)
        self.assertIsNone(tool.preflight)
        schema = tool.public_contract()
        self.assertEqual(set(schema), {"name", "description", "input_schema"})
        self.assertEqual(set(schema["input_schema"]["properties"]), {"activity_id", "expected_name"})
        self.assertFalse(schema["input_schema"]["additionalProperties"])

    def test_review_uses_database_fields_and_explains_whole_local_recurrence(self):
        identifier = self.add(activity_type="weekly", date=None, weekday="Monday", source="UoA",
                              external_id="private-external-id", active_start_date="2026-07-01",
                              active_end_date="2026-11-01")
        proposal = self.proposal(activity_id=identifier)
        reviewed = describe_activity_proposals(self.connection, [proposal])[0]
        description = reviewed.display_description
        self.assertIn(f"Id: {identifier}", description)
        self.assertIn("Subject: MATHS 102", description)
        self.assertIn("Source: UoA", description)
        self.assertIn("entire recurring activity", description)
        self.assertIn("source feed is unchanged", description)
        self.assertNotIn("private-external-id", description)
        self.assertEqual(reviewed.arguments, proposal.arguments)
        self.assertEqual(reviewed.status, ActionStatus.PENDING_APPROVAL)
        self.assertIsNotNone(activities.get_activity_by_id(self.connection, identifier))

    def test_confirm_imported_target_cascades_only_its_uid_mappings(self):
        self.connection.executemany("INSERT INTO uoa_activity_external_ids (activity_id, external_id) VALUES (?, ?)",
            [(self.first_id, "uid-1"), (self.first_id, "uid-2"), (self.second_id, "uid-3")])
        self.connection.commit()
        proposal = self.proposal()
        self.approval.decide(proposal.id, ApprovalDecision.APPROVE)
        self.assertTrue(self.executor.execute(proposal.id).success)
        self.assertEqual(self.connection.execute("SELECT activity_id, external_id FROM uoa_activity_external_ids").fetchall(),
                         [(self.second_id, "uid-3")])

    def test_service_rechecks_under_transaction_and_rolls_back_failure(self):
        def fail_after_delete(connection, identifier, *, commit):
            activities.delete_activity(connection, identifier, commit=commit)
            raise sqlite3.OperationalError("private database details")
        with patch.object(activity_service, "delete_activity", side_effect=fail_after_delete):
            with self.assertRaises(sqlite3.OperationalError):
                activity_service.delete_activity_record(self.connection, self.first_id, "Study")
        self.assertIsNotNone(activities.get_activity_by_id(self.connection, self.first_id))
        self.assertFalse(self.connection.in_transaction)
        with self.assertRaises(activity_service.ActivityValidationError):
            activity_service.delete_activity_record(self.connection, self.first_id, "Renamed")
        self.assertIsNotNone(activities.get_activity_by_id(self.connection, self.first_id))
        self.assertFalse(self.connection.in_transaction)

    def test_standalone_delete_keeps_its_existing_commit_behavior(self):
        self.assertEqual(activities.delete_activity(self.connection, self.first_id), 1)
        self.assertFalse(self.connection.in_transaction)

    def test_preflight_refusal_never_runs_handler_but_handler_errors_remain_uncertain(self):
        handler = Mock()
        preflight = Mock(side_effect=ToolPreconditionError("Activity no longer exists."))
        tool = Tool("delete_activity", "Delete", DeleteActivityArguments, handler, preflight)
        arguments = {"activity_id": self.first_id, "expected_name": "Study"}
        with self.assertRaises(ToolPreconditionError):
            tool.execute(arguments)
        handler.assert_not_called()
        handler.side_effect = ToolPreconditionError("Raised after handler started")
        tool = Tool("delete_activity", "Delete", DeleteActivityArguments, handler)
        with self.assertRaises(ToolOutcomeUnconfirmedError):
            tool.execute(arguments)


if __name__ == "__main__":
    unittest.main()
