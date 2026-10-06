"""Approved real creation path, using disposable SQLite and no model calls."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.app.ai.actions.activity_tool import AddActivityTool, create_activity_tool_registry
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import (
    ActionProposal, ActionStatus, AddActivityArguments, ApprovalDecision,
)
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.registry import UnknownToolError, create_proposal_tool_registry
from backend.app.database import create_tables
from backend.app.planner import activities, activity_service


def activity_arguments(**changes):
    fields = {
        "name": " Study Maths ", "category": " Study ", "subject": " MATHS 102 ",
        "activity_type": "one_time", "date": "2026-10-09", "weekday": None,
        "start_time": "18:00", "end_time": "19:00",
    }
    return {**fields, **changes}


class AddActivityToolTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        create_tables(self.connection)
        self.registry = create_activity_tool_registry(self.connection)
        self.approval = ApprovalBoundary()
        self.executor = ActionExecutor(self.registry, self.approval)

    def proposal(self, arguments=None, tool_name="add_activity"):
        return self.approval.register(ActionProposal(
            tool_name=tool_name,
            arguments=activity_arguments() if arguments is None else arguments,
            display_title="Add Activity", display_description="Create a study session.",
        ))

    def approve(self, proposal):
        self.approval.decide(proposal.id, ApprovalDecision.APPROVE)

    def test_approved_tool_reuses_service_and_creates_expected_activity(self):
        proposal = self.proposal()
        self.approve(proposal)
        with patch.object(activity_service, "prepare_new_activity",
                          wraps=activity_service.prepare_new_activity) as prepare:
            with patch.object(activity_service, "create_activity_record",
                              wraps=activity_service.create_activity_record) as create:
                result = self.executor.execute(proposal.id)
        prepare.assert_called_once_with({
            **activity_arguments(), "name": "Study Maths", "category": "Study", "subject": "MATHS 102",
        })
        create.assert_called_once_with(self.connection, (
            ["name", "category", "subject", "activity_type", "date", "weekday", "start_time", "end_time"],
            ["Study Maths", "Study", "MATHS 102", "one_time", "2026-10-09", None, "18:00", "19:00"],
        ))
        self.assertTrue(result.success)
        row = activities.get_activity_by_id(self.connection, result.result["activity_id"])
        self.assertEqual(row[1:9], ("Study Maths", "Study", "MATHS 102", "one_time",
                                   "2026-10-09", None, "18:00", "19:00"))
        self.assertEqual(row[9:13], (None, None, "Manual", None))
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.COMPLETED)
        self.assertFalse(self.connection.in_transaction)
        json.dumps(result.model_dump(mode="json"))

    def test_pending_proposal_never_reaches_creation(self):
        proposal = self.proposal()
        with patch.object(activity_service, "prepare_new_activity") as prepare:
            with patch.object(activity_service, "create_activity_record") as create:
                result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        prepare.assert_not_called()
        create.assert_not_called()
        self.assertEqual(activities.get_all_activities(self.connection), [])

    def test_rejected_proposal_never_reaches_creation(self):
        proposal = self.proposal()
        self.approval.decide(proposal.id, ApprovalDecision.REJECT)
        with patch.object(activity_service, "create_activity_record") as create:
            result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        create.assert_not_called()
        self.assertEqual(activities.get_all_activities(self.connection), [])

    def test_invalid_contract_arguments_do_not_mutate_sqlite(self):
        missing_name = activity_arguments()
        del missing_name["name"]
        invalid = [
            missing_name, activity_arguments(name=" "), activity_arguments(category=" "),
            activity_arguments(date="2026-02-30"), activity_arguments(start_time="25:00"),
            activity_arguments(end_time="17:00"), activity_arguments(activity_type="monthly"),
            activity_arguments(weekday="Monday"), activity_arguments(id=7),
            activity_arguments(source="Canvas"), activity_arguments(external_id="private-uid"),
        ]
        with patch.object(activity_service, "prepare_new_activity") as prepare:
            with patch.object(activity_service, "create_activity_record") as create:
                for arguments in invalid:
                    with self.subTest(arguments=arguments):
                        proposal = self.proposal(arguments)
                        self.approve(proposal)
                        result = self.executor.execute(proposal.id)
                        self.assertFalse(result.success)
                        self.assertEqual(result.error, "The tool arguments are invalid.")
                prepare.assert_not_called()
                create.assert_not_called()
        self.assertEqual(activities.get_all_activities(self.connection), [])

    def test_domain_validation_runs_before_creation(self):
        proposal = self.proposal()
        self.approve(proposal)
        error = activity_service.ActivityValidationError(status_code=400, detail="Domain rejection")
        with patch.object(activity_service, "prepare_new_activity", side_effect=error) as prepare:
            with patch.object(activity_service, "create_activity_record") as create:
                result = self.executor.execute(proposal.id)
        prepare.assert_called_once()
        create.assert_not_called()
        self.assertFalse(result.success)
        self.assertEqual(activities.get_all_activities(self.connection), [])

    def test_weekly_daily_and_date_only_use_existing_null_rules(self):
        for changes, expected in (
            ({"activity_type": "weekly", "date": None, "weekday": "Monday"}, ("weekly", None, "Monday")),
            ({"activity_type": "daily", "date": None}, ("daily", None, None)),
            ({"start_time": None, "end_time": None}, ("one_time", "2026-10-09", None)),
        ):
            with self.subTest(changes=changes):
                proposal = self.proposal(activity_arguments(**changes))
                self.approve(proposal)
                result = self.executor.execute(proposal.id)
                self.assertTrue(result.success)
                row = activities.get_activity_by_id(self.connection, result.result["activity_id"])
                self.assertEqual(row[4:7], expected)
                self.assertEqual(row[7:9], (changes.get("start_time", "18:00"),
                                           changes.get("end_time", "19:00")))

    def test_completed_proposal_does_not_insert_a_second_row(self):
        proposal = self.proposal()
        self.approve(proposal)
        self.assertTrue(self.executor.execute(proposal.id).success)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.assertEqual(len(activities.get_all_activities(self.connection)), 1)

    def test_created_activity_is_committed_and_readable_after_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.db"
            proposal = self.proposal()
            self.approve(proposal)
            with closing(sqlite3.connect(path)) as connection:
                create_tables(connection)
                executor = ActionExecutor(create_activity_tool_registry(connection), self.approval)
                result = executor.execute(proposal.id)
                self.assertTrue(result.success)
            with closing(sqlite3.connect(path)) as connection:
                row = activities.get_activity_by_id(connection, result.result["activity_id"])
                self.assertEqual(row[1], "Study Maths")
                self.assertEqual(len(activities.get_all_activities(connection)), 1)

    def test_storage_failure_is_controlled_without_exposing_details(self):
        proposal = self.proposal()
        self.approve(proposal)
        with patch.object(activity_service, "create_activity_record",
                          side_effect=sqlite3.OperationalError("private storage details")):
            result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertNotIn("private storage details", result.model_dump_json())
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.assertEqual(activities.get_all_activities(self.connection), [])

    def test_unknown_tool_cannot_create_an_activity(self):
        proposal = self.proposal(tool_name="unknown_tool")
        self.approve(proposal)
        result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "The requested tool is not registered.")
        self.assertEqual(activities.get_all_activities(self.connection), [])
        with self.assertRaises(UnknownToolError):
            self.registry.resolve("add_exam")

    def test_post_insert_read_failure_preserves_uncertain_outcome_and_blocks_replay(self):
        proposal = self.proposal()
        self.approve(proposal)
        with patch.object(activity_service, "get_activity_by_id",
                          side_effect=sqlite3.OperationalError("private storage details")):
            result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertIn("unconfirmed", result.message)
        self.assertNotIn("private storage details", result.model_dump_json())
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.assertEqual(len(activities.get_all_activities(self.connection)), 1)

    def test_registration_and_public_contract_do_not_create_or_expose_metadata(self):
        tool = self.registry.resolve("add_activity")
        self.assertIsInstance(tool, AddActivityTool)
        self.assertIs(tool.arguments_model, AddActivityArguments)
        self.assertIsNotNone(tool.handler)
        self.assertEqual(set(tool.public_contract()), {"name", "description", "input_schema"})
        self.assertEqual(set(tool.public_contract()["input_schema"]["properties"]), set(activity_arguments()))
        self.assertIsNone(create_proposal_tool_registry().resolve("add_activity").handler)
        self.assertEqual(activities.get_all_activities(self.connection), [])


if __name__ == "__main__":
    unittest.main()
