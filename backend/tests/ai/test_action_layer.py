"""Stage 8 contract/lifecycle tests: fake tools only, no DB or model calls."""

import json
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import (
    ActionLayerError, ActionProposal, ActionResult, ActionRoute, ActionStatus, ApprovalDecision,
    AddActivityArguments,
)
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.planning import ResponsePlanner
from backend.app.ai.actions.registry import ToolRegistry, UnknownToolError, create_proposal_tool_registry
from backend.app.ai.actions.routing import route_agent_output
from backend.app.ai.actions.tools import InvalidToolArgumentsError, Tool, ToolExecutionUnavailableError
from backend.app.ai.agent.contracts import validate_agent_proposal
from backend.tests.paths import PROJECT_DIRECTORY


class FakeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1)


class ActionLayerTests(unittest.TestCase):
    def setUp(self):
        self.handler = Mock(return_value={"echo": "Study"})
        self.tool = Tool("fake_action", "Echo a value without changing app data.", FakeArguments, self.handler)
        self.registry = ToolRegistry()
        self.registry.register(self.tool)
        self.approval = ApprovalBoundary()
        self.executor = ActionExecutor(self.registry, self.approval)

    def propose(self, **overrides):
        action = {"tool": "fake_action", "arguments": {"label": "Study"}, **overrides}
        routed = route_agent_output({"message": "Only a proposal.", "actions": [action]},
                                    self.registry, self.approval)
        return routed.proposals[0]

    def approve(self, proposal):
        return self.approval.decide(proposal.id, ApprovalDecision.APPROVE)

    def test_new_proposal_is_pending_and_has_backend_display_fields(self):
        proposal = self.propose()
        self.assertEqual(proposal.status, ActionStatus.PENDING_APPROVAL)
        self.assertTrue(proposal.requires_approval)
        self.assertEqual(proposal.action_type, "tool_action")
        self.assertEqual(proposal.display_title, "Fake Action")
        self.assertIn("Label: Study", proposal.display_description)
        self.assertEqual(self.approval.get(proposal.id), proposal)
        self.handler.assert_not_called()
        json.dumps(proposal.model_dump(mode="json"))

    def test_normal_message_has_no_action_route(self):
        result = route_agent_output({"message": "No change needed.", "actions": []},
                                    self.registry, self.approval)
        self.assertEqual(result.route, ActionRoute.NONE)
        self.assertEqual(result.proposals, [])
        self.handler.assert_not_called()

    def test_response_planning_is_a_placeholder_only(self):
        result = route_agent_output({"message": "Future planning.", "actions": []},
                                    self.registry, self.approval, response_plan_requested=True)
        self.assertEqual(result.route, ActionRoute.RESPONSE_PLAN)
        self.assertEqual(result.proposals, [])
        self.handler.assert_not_called()
        with self.assertRaises(TypeError):
            ResponsePlanner()

    def test_response_plan_and_actions_cannot_be_selected_together(self):
        with self.assertRaises(ActionLayerError):
            route_agent_output({"actions": [{"tool": "fake_action", "arguments": {"label": "Study"}}]},
                               self.registry, self.approval, response_plan_requested=True)
        self.handler.assert_not_called()

    def test_unapproved_proposal_does_not_execute(self):
        proposal = self.propose()
        result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "The proposal is not approved for execution.")
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.PENDING_APPROVAL)
        self.handler.assert_not_called()

    def test_rejected_proposal_cannot_execute(self):
        proposal = self.propose()
        rejected = self.approval.decide(proposal.id, ApprovalDecision.REJECT)
        self.assertEqual(rejected.status, ActionStatus.REJECTED)
        self.assertFalse(self.executor.execute(proposal.id).success)
        with self.assertRaises(ActionLayerError):
            self.approve(proposal)
        self.handler.assert_not_called()

    def test_approval_itself_does_not_execute(self):
        proposal = self.propose()
        approved = self.approve(proposal)
        self.assertEqual(approved.status, ActionStatus.APPROVED)
        self.handler.assert_not_called()

    def test_approved_fake_tool_returns_action_result(self):
        proposal = self.propose()
        self.approve(proposal)
        result = self.executor.execute(proposal.id)
        self.assertIsInstance(result, ActionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.proposal_id, proposal.id)
        self.assertEqual(result.result, {"echo": "Study"})
        self.assertIsNone(result.error)
        self.handler.assert_called_once_with({"label": "Study"})
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.COMPLETED)
        json.dumps(result.model_dump(mode="json"))

    def test_executor_marks_executing_before_the_handler_runs(self):
        proposal = self.propose()
        self.approve(proposal)

        def fake_handler(arguments):
            self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.EXECUTING)
            return {"echo": arguments["label"]}

        self.handler.side_effect = fake_handler
        self.assertTrue(self.executor.execute(proposal.id).success)

    def test_completed_action_cannot_execute_twice(self):
        proposal = self.propose()
        self.approve(proposal)
        self.assertTrue(self.executor.execute(proposal.id).success)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.handler.assert_called_once()

    def test_concurrent_attempts_claim_one_execution_only(self):
        proposal = self.propose()
        self.approve(proposal)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.executor.execute, [proposal.id, proposal.id]))
        self.assertEqual(sum(result.success for result in results), 1)
        self.handler.assert_called_once()

    def test_client_snapshot_cannot_approve_or_change_stored_arguments(self):
        proposal = self.propose()
        forged = proposal.model_copy(update={"status": ActionStatus.APPROVED}, deep=True)
        forged.arguments["label"] = "Changed outside the approval boundary"
        self.assertFalse(self.executor.execute(forged.id).success)
        self.assertEqual(self.approval.get(proposal.id).arguments, {"label": "Study"})
        with self.assertRaises(ActionLayerError):
            self.approval.register(forged)
        self.handler.assert_not_called()

    def test_approval_cannot_be_bypassed_in_the_request_or_proposal(self):
        for field, value in (("status", "approved"), ("requires_approval", False), ("id", "supplied-id")):
            with self.subTest(field=field), self.assertRaises(ActionLayerError):
                self.propose(**{field: value})
        proposal = self.propose()
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({**proposal.model_dump(), "requires_approval": False})
        with self.assertRaises(ValidationError):
            self.approval.register(proposal.model_copy(update={"requires_approval": False}))
        for decision in (True, False, "approve", None):
            with self.subTest(decision=decision), self.assertRaises(ActionLayerError):
                self.approval.decide(proposal.id, decision)
        self.handler.assert_not_called()

    def test_registry_resolves_fake_tool_and_rejects_duplicate_names(self):
        self.assertIs(self.registry.resolve("fake_action"), self.tool)
        with self.assertRaises(ActionLayerError):
            self.registry.register(self.tool)
        with self.assertRaises(UnknownToolError):
            self.registry.resolve("unknown_tool")

    def test_public_contract_contains_only_public_name_description_schema(self):
        contracts = self.registry.public_contracts()
        self.assertEqual(set(contracts[0]), {"name", "description", "input_schema"})
        self.assertEqual(contracts[0]["input_schema"]["properties"]["label"]["type"], "string")
        contracts[0]["input_schema"]["properties"].clear()
        self.assertIn("label", self.registry.public_contracts()[0]["input_schema"]["properties"])

    def test_unknown_tool_and_invalid_arguments_produce_controlled_router_errors(self):
        for action in (
            {"tool": "unknown_tool", "arguments": {"label": "Study"}},
            {"tool": "fake_action", "arguments": {}},
            {"tool": "fake_action", "arguments": {"label": 42}},
            {"tool": "fake_action", "arguments": {"label": "Study", "sql": "not allowed"}},
            {"tool": "fake_action", "arguments": {"label": ""}},
        ):
            with self.subTest(action=action), self.assertRaises(ActionLayerError):
                route_agent_output({"actions": [action]}, self.registry, self.approval)
        self.handler.assert_not_called()

    def test_invalid_action_batch_registers_no_partial_proposals(self):
        with patch.object(self.approval, "register", wraps=self.approval.register) as register:
            with self.assertRaises(ActionLayerError):
                route_agent_output({"actions": [
                    {"tool": "fake_action", "arguments": {"label": "Study"}},
                    {"tool": "unknown_tool", "arguments": {}},
                ]}, self.registry, self.approval)
        register.assert_not_called()

    def test_unknown_proposal_and_unknown_registered_tool_return_failures(self):
        self.assertFalse(self.executor.execute("unknown-proposal").success)
        proposal = self.approval.register(ActionProposal(
            tool_name="unknown_tool", arguments={}, display_title="Unknown", display_description="",
        ))
        self.approve(proposal)
        result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "The requested tool is not registered.")
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)

    def test_tool_failure_is_safe_and_cannot_be_retried_automatically(self):
        proposal = self.propose()
        self.approve(proposal)
        self.handler.side_effect = RuntimeError("private tool internals must never appear")
        result = self.executor.execute(proposal.id)
        self.assertFalse(result.success)
        self.assertNotIn("private tool internals", result.model_dump_json())
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.handler.assert_called_once()

    def test_executor_revalidates_arguments_and_rejects_non_json_results(self):
        proposal = self.approval.register(ActionProposal(
            tool_name="fake_action", arguments={"label": 42}, display_title="Fake", display_description="",
        ))
        self.approve(proposal)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.handler.assert_not_called()
        valid = self.propose()
        self.approve(valid)
        self.handler.return_value = {"not_json": object()}
        self.assertFalse(self.executor.execute(valid.id).success)
        self.assertEqual(self.approval.get(valid.id).status, ActionStatus.FAILED)

    def test_state_change_with_invalid_result_is_reported_as_unconfirmed(self):
        fake_rows = []

        def handler(arguments):
            fake_rows.append(arguments)
            return {"created": object()}

        self.handler.side_effect = handler
        proposal = self.propose()
        self.approve(proposal)
        result = self.executor.execute(proposal.id)
        self.assertEqual(len(fake_rows), 1)
        self.assertFalse(result.success)
        self.assertIsNone(result.result)
        self.assertIn("unconfirmed", result.message)
        self.assertIn("Check the app", result.message)
        self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
        self.assertFalse(self.executor.execute(proposal.id).success)
        self.assertEqual(len(fake_rows), 1)
        json.dumps(result.model_dump(mode="json"))

    def test_handler_errors_after_state_change_are_never_preflight_refusals(self):
        for error_type in (RuntimeError, UnknownToolError, InvalidToolArgumentsError,
                           ToolExecutionUnavailableError):
            with self.subTest(error_type=error_type):
                fake_rows = []

                def handler(arguments):
                    fake_rows.append(arguments)
                    raise error_type("private details")

                self.handler.side_effect = handler
                proposal = self.propose()
                self.approve(proposal)
                result = self.executor.execute(proposal.id)
                self.assertFalse(result.success)
                self.assertEqual(result.error, "The tool outcome could not be confirmed.")
                self.assertIn("unconfirmed", result.message)
                self.assertNotIn("private details", result.model_dump_json())
                self.assertEqual(self.approval.get(proposal.id).status, ActionStatus.FAILED)
                self.assertFalse(self.executor.execute(proposal.id).success)
                self.assertEqual(len(fake_rows), 1)

    def test_preflight_refusal_reports_that_this_attempt_did_not_run(self):
        proposal = self.approval.register(ActionProposal(
            tool_name="fake_action", arguments={"label": 42}, display_title="Fake", display_description="",
        ))
        self.approve(proposal)
        result = self.executor.execute(proposal.id)
        self.assertEqual(result.error, "The tool arguments are invalid.")
        self.assertEqual(result.message, "This execution attempt did not run the action.")
        self.handler.assert_not_called()

    def test_existing_add_activity_contract_routes_but_cannot_execute(self):
        arguments = {
            "name": "Maths revision", "category": "Study", "subject": "MATHS 102",
            "activity_type": "one_time", "date": "2026-10-09", "weekday": None,
            "start_time": "18:00", "end_time": "19:00",
        }
        output = {"message": "Would you like this session?", "actions": [
            {"tool": "add_activity", "arguments": arguments},
        ]}
        registry = create_proposal_tool_registry()
        self.assertIs(registry.resolve("add_activity").arguments_model, AddActivityArguments)
        self.assertEqual([tool["name"] for tool in registry.public_contracts()], ["add_activity"])
        validated = validate_agent_proposal(output).model_dump()
        routed = route_agent_output(validated, registry, self.approval)
        self.assertEqual(routed.route, ActionRoute.TOOL_ACTION)
        proposal = routed.proposals[0]
        self.assertEqual(proposal.arguments, arguments)
        self.approve(proposal)
        result = ActionExecutor(registry, self.approval).execute(proposal.id)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Execution is not available for this tool.")
        # Today's provider/API response format is still the same contract.
        self.assertEqual(validate_agent_proposal(output).model_dump(), validated)
        with self.assertRaises(UnknownToolError):
            registry.resolve("add_exam")

    def test_proposal_ids_are_distinct_and_cannot_be_overwritten(self):
        first = self.propose()
        second = self.propose()
        self.assertNotEqual(first.id, second.id)
        with self.assertRaises(ActionLayerError):
            self.approval.register(first)

    def test_result_contract_rejects_contradictory_outcomes(self):
        for value in (
            {"success": True, "error": "Cannot be both success and failure"},
            {"success": False, "error": None},
            {"success": False, "error": "Failed", "result": {"id": 1}},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ActionResult(proposal_id="test", message="Test", **value)

    def test_action_layer_imports_without_planner_storage_http_or_openai(self):
        code = """
import sys
for name in ('openai', 'sqlite3', 'fastapi', 'backend.app.ai.agent.service',
             'backend.app.planner.activities', 'backend.app.planner.exams'):
    sys.modules[name] = None
from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.routing import route_agent_output
from backend.app.ai.actions.planning import ResponsePlanner
registry = create_proposal_tool_registry()
assert registry.resolve('add_activity').handler is None
assert route_agent_output({'message': 'Hello', 'actions': []}, registry,
                          ApprovalBoundary()).route.value == 'none'
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
