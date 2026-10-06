"""Explicit tool discovery; no dynamic imports or planner tool handlers."""

from backend.app.ai.actions.contracts import ActionLayerError, AddActivityArguments
from backend.app.ai.actions.tools import Tool


class UnknownToolError(ActionLayerError):
    pass


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if not isinstance(tool, Tool):
            raise ValueError("Register a trusted Tool instance.")
        if tool.name in self._tools:
            raise ActionLayerError("A tool with this name is already registered.")
        self._tools[tool.name] = tool

    def resolve(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError("The requested tool is not registered.") from None

    def public_contracts(self):
        return [self._tools[name].public_contract() for name in sorted(self._tools)]


def create_proposal_tool_registry():
    """Reuse today's allowed action schema, with NO executable handler."""
    registry = ToolRegistry()
    registry.register(Tool(
        name="add_activity",
        description="Propose a new activity for user confirmation. This request never saves it automatically.",
        arguments_model=AddActivityArguments,
    ))
    return registry
