"""Action contracts and explicit discovery, independently of lifecycle code."""

import json
import unittest

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.app.ai.actions.contracts import (
    ActionLayerError, ActionProposal, ActionResult, ActionStatus, AddActivityArguments,
)
from backend.app.ai.actions.planning import ResponsePlanner
from backend.app.ai.actions.registry import ToolRegistry, UnknownToolError, create_proposal_tool_registry
from backend.app.ai.actions.tools import InvalidToolArgumentsError, Tool, ToolExecutionUnavailableError


class EchoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class ActionContractTests(unittest.TestCase):
    def test_proposal_defaults_to_pending_with_required_approval(self):
        proposal = ActionProposal(tool_name="echo", arguments={"text": "Hello"},
                                  display_title="Echo", display_description="Text: Hello")
        self.assertEqual(proposal.status, ActionStatus.PENDING_APPROVAL)
        self.assertTrue(proposal.requires_approval)
        self.assertEqual(proposal.action_type, "tool_action")
        self.assertEqual(json.loads(proposal.model_dump_json())["status"], "pending_approval")
        with self.assertRaises(ValidationError):
            proposal.status = ActionStatus.APPROVED
        with self.assertRaises(ValidationError):
            ActionProposal.model_validate({**proposal.model_dump(), "requires_approval": False})

    def test_action_results_are_json_ready_and_reject_contradictions(self):
        result = ActionResult(proposal_id="example", success=True, result={"echo": "Hello"},
                              message="Echo completed.")
        self.assertEqual(json.loads(result.model_dump_json())["result"], {"echo": "Hello"})
        with self.assertRaises(ValidationError):
            ActionResult(proposal_id="example", success=True, error="Failed", message="Test")
        with self.assertRaises(ValidationError):
            ActionResult(proposal_id="example", success=False, message="Test")

    def test_registry_is_explicit_and_does_not_overwrite_tools(self):
        registry = ToolRegistry()
        tool = Tool("echo", "Echo for offline tests only.", EchoArguments)
        registry.register(tool)
        self.assertIs(registry.resolve("echo"), tool)
        with self.assertRaises(ActionLayerError):
            registry.register(tool)
        with self.assertRaises(UnknownToolError):
            registry.resolve("unknown")

    def test_tool_contract_exposes_schema_not_handler(self):
        tool = Tool("echo", "Echo for offline tests only.", EchoArguments, lambda args: args)
        contract = tool.public_contract()
        self.assertEqual(set(contract), {"name", "description", "input_schema"})
        self.assertEqual(contract["input_schema"]["required"], ["text"])
        self.assertFalse(contract["input_schema"]["additionalProperties"])

    def test_tool_validates_strict_arguments_and_missing_handler_refuses_execution(self):
        tool = Tool("echo", "Echo for offline tests only.", EchoArguments)
        self.assertEqual(tool.validate({"text": "Hello"}), {"text": "Hello"})
        for arguments in ({}, {"text": 42}, {"text": "Hello", "sql": "not allowed"}):
            with self.subTest(arguments=arguments), self.assertRaises(InvalidToolArgumentsError):
                tool.validate(arguments)
        with self.assertRaises(ToolExecutionUnavailableError):
            tool.execute({"text": "Hello"})

    def test_default_registry_reuses_add_activity_schema_without_execution(self):
        registry = create_proposal_tool_registry()
        tool = registry.resolve("add_activity")
        self.assertIs(tool.arguments_model, AddActivityArguments)
        self.assertIsNone(tool.handler)
        self.assertEqual([contract["name"] for contract in registry.public_contracts()], ["add_activity", "delete_activity", "edit_activity"])
        with self.assertRaises(UnknownToolError):
            registry.resolve("add_exam")

    def test_bad_tool_definitions_are_rejected(self):
        for name, description, model, handler in (
            ("", "Description", EchoArguments, None),
            ("INSERT SQL", "Description", EchoArguments, None),
            ("echo", "", EchoArguments, None),
            ("echo", "Description", dict, None),
            ("echo", "Description", EchoArguments, "not callable"),
        ):
            with self.subTest(name=name, description=description), self.assertRaises(ValueError):
                Tool(name, description, model, handler)

    def test_response_planner_is_an_interface_not_a_live_implementation(self):
        with self.assertRaises(TypeError):
            ResponsePlanner()


if __name__ == "__main__":
    unittest.main()
