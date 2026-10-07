"""Atomic, approval-gated edits on disposable data; no paid API calls."""

import sqlite3
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.app.ai.actions.activity_tool import create_activity_tool_registry, describe_activity_proposals
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ActionProposal, ApprovalDecision, EditActivityArguments
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.database import create_tables
from backend.app.planner import activities, activity_service


def change(column, value):
    return {"column_name": column, "new_value": value}


class EditActivityToolTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA foreign_keys = ON")
        create_tables(self.connection)
        self.identifier = self.add()
        self.other_id = self.add()
        self.approval = ApprovalBoundary()
        self.executor = ActionExecutor(create_activity_tool_registry(self.connection), self.approval)

    def add(self, **changes):
        fields = {"name": "Study", "category": "Study", "subject": "MATHS 102",
                  "activity_type": "one_time", "date": "2026-10-09", "weekday": None,
                  "start_time": "18:00", "end_time": "19:00", **changes}
        return activities.add_activity(self.connection, list(fields), list(fields.values()))

    def proposal(self, changes=None, **arguments):
        return self.approval.register(ActionProposal(tool_name="edit_activity",
            arguments={"activity_id": self.identifier, "expected_name": "Study",
                       "changes": changes if changes is not None else [change("name", "Revision")], **arguments},
            display_title="Edit Activity", display_description="Review changes."))

    def row(self, identifier=None):
        return activities.get_activity_by_id(self.connection, self.identifier if identifier is None else identifier)

    def execute(self, proposal):
        self.approval.decide(proposal.id, ApprovalDecision.APPROVE)
        return self.executor.execute(proposal.id)

    def test_pending_and_cancelled_edit_never_reaches_update(self):
        before = self.row()
        proposal = self.proposal()
        with patch.object(activity_service, "update_activity_fields") as update:
            self.assertFalse(self.executor.execute(proposal.id).success)
            self.approval.decide(proposal.id, ApprovalDecision.REJECT)
            self.assertFalse(self.executor.execute(proposal.id).success)
        update.assert_not_called()
        self.assertEqual(self.row(), before)

    def test_confirm_multiple_changes_reuses_crud_and_keeps_same_id(self):
        other = self.row(self.other_id)
        proposal = self.proposal([change("name", "Revision"), change("start_time", "19:00"), change("end_time", "20:00")])
        with patch.object(activity_service, "edit_activity", wraps=activities.edit_activity) as edit:
            result = self.execute(proposal)
        self.assertTrue(result.success)
        self.assertEqual(edit.call_count, 3)
        for call in edit.call_args_list:
            self.assertEqual(call.args[:2], (self.connection, self.identifier))
            self.assertEqual(call.kwargs, {"commit": False})
        self.assertEqual(self.row()[0], self.identifier)
        self.assertEqual(self.row()[1], "Revision")
        self.assertEqual(self.row()[7:9], ("19:00", "20:00"))
        self.assertEqual(self.row(self.other_id), other)
        self.assertEqual(len(activities.get_all_activities(self.connection)), 2)
        self.assertFalse(self.connection.in_transaction)
        self.assertFalse(self.executor.execute(proposal.id).success)

    def test_invalid_time_pair_and_missing_recurrence_field_fail_before_update(self):
        before = self.row()
        for changes in ([change("start_time", "20:00")], [change("activity_type", "weekly")],
                        [change("weekday", "Monday")], [change("name", "Study")]):
            with self.subTest(changes=changes), patch.object(activity_service, "update_activity_fields") as update:
                result = self.execute(self.proposal(changes))
                self.assertFalse(result.success)
                self.assertIn("did not run", result.message)
                update.assert_not_called()
                self.assertEqual(self.row(), before)

    def test_recurrence_changes_clear_unused_fields(self):
        for changes, expected in (
            ([change("activity_type", "weekly"), change("weekday", "Monday")], ("weekly", None, "Monday")),
            ([change("activity_type", "daily")], ("daily", None, None)),
            ([change("activity_type", "one_time"), change("date", "2026-10-10")], ("one_time", "2026-10-10", None)),
        ):
            with self.subTest(changes=changes):
                self.assertTrue(self.execute(self.proposal(changes)).success)
                self.assertEqual(self.row()[4:7], expected)

    def test_date_only_subject_and_optional_times_can_be_cleared(self):
        result = self.execute(self.proposal([change("subject", None), change("start_time", None), change("end_time", None)]))
        self.assertTrue(result.success)
        self.assertIsNone(self.row()[3])
        self.assertEqual(self.row()[7:9], (None, None))
        self.assertEqual(self.row()[5], "2026-10-09")

    def test_metadata_active_range_and_uoa_mappings_are_preserved(self):
        for source in ("Manual", "Canvas", "UoA"):
            with self.subTest(source=source):
                identifier = self.add(source=source, external_id="private-id", activity_type="weekly",
                                      date=None, weekday="Monday", active_start_date="2026-07-01", active_end_date="2026-11-01")
                self.connection.execute("INSERT INTO uoa_activity_external_ids (activity_id, external_id) VALUES (?, ?)",
                                        (identifier, "original-uoa-uid"))
                self.connection.commit()
                before = self.row(identifier)
                proposal = self.proposal([change("name", "Updated class"), change("weekday", "Tuesday")], activity_id=identifier)
                self.assertTrue(self.execute(proposal).success)
                after = self.row(identifier)
                self.assertEqual(after[0], before[0])
                self.assertEqual(after[9:], before[9:])
                self.assertEqual(self.connection.execute("SELECT external_id FROM uoa_activity_external_ids WHERE activity_id=?", (identifier,)).fetchall(),
                                 [("original-uoa-uid",)])

    def test_read_only_preview_shows_before_after_and_automatic_null_clear(self):
        proposal = self.proposal([change("activity_type", "weekly"), change("weekday", "Monday")])
        before = self.row()
        reviewed = describe_activity_proposals(self.connection, [proposal])[0]
        self.assertIn("Activity type: one_time → weekly", reviewed.display_description)
        self.assertIn("Date: 2026-10-09 → Not set", reviewed.display_description)
        self.assertIn("Weekday: Not set → Monday", reviewed.display_description)
        self.assertIn("not just one calendar occurrence", reviewed.display_description)
        self.assertEqual(self.row(), before)
        self.assertEqual(reviewed.id, proposal.id)

    def test_missing_or_renamed_target_cannot_be_edited(self):
        before = self.row()
        for arguments in ({"activity_id": 999}, {"expected_name": "Different"}):
            with self.subTest(arguments=arguments):
                result = self.execute(self.proposal(**arguments))
                self.assertFalse(result.success)
                self.assertIn("Request a new proposal", result.error)
                self.assertEqual(self.row(), before)

    def test_partial_crud_failure_rolls_back_every_field_and_is_sanitized(self):
        original = activities.edit_activity
        before = self.row()
        calls = []
        def fail_on_second(*args, **kwargs):
            calls.append(args)
            original(*args, **kwargs)
            if len(calls) == 2:
                raise sqlite3.OperationalError("private storage details")
        proposal = self.proposal([change("name", "Revision"), change("subject", "COMPSCI 130")])
        with patch.object(activity_service, "edit_activity", side_effect=fail_on_second):
            result = self.execute(proposal)
        self.assertFalse(result.success)
        self.assertNotIn("private storage details", result.model_dump_json())
        self.assertEqual(self.row(), before)
        self.assertFalse(self.connection.in_transaction)

    def test_strict_contract_rejects_protected_fields_duplicates_and_bad_values(self):
        valid = {"activity_id": self.identifier, "expected_name": "Study", "changes": [change("name", "Revision")]}
        invalid_changes = [[], [change("name", " ")], [change("category", None)],
                           [change("activity_type", "monthly")], [change("date", "2026-02-30")],
                           [change("weekday", "Someday")], [change("start_time", "25:00")],
                           [change("end_time", "9:00")], [change("subject", 42)],
                           [change("name", "A"), change("name", "B")],
                           [{**change("name", "A"), "approved": True}]]
        invalid_changes += [[change(field, "bad")] for field in ("id", "source", "external_id", "active_start_date", "active_end_date")]
        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EditActivityArguments.model_validate({**valid, "changes": changes})
        for extra in ({"activity_id": True}, {"activity_id": "1"}, {"expected_name": " "}, {"owner_id": "forged"}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                EditActivityArguments.model_validate({**valid, **extra})

    def test_planner_also_rejects_arbitrary_column_names(self):
        before = self.row()
        with self.assertRaises(activity_service.ActivityValidationError):
            activity_service.prepare_activity_update(self.connection, self.identifier, "Study", [change("source", "Canvas")])
        self.assertEqual(self.row(), before)


if __name__ == "__main__":
    unittest.main()
