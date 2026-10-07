"""Explicit tool discovery; no dynamic imports or planner tool handlers."""

from backend.app.ai.actions.contracts import ActionLayerError, AddActivityArguments, DeleteActivityArguments, EditActivityArguments
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
    registry.register(Tool(
        name="delete_activity",
        description="Propose permanently deleting ONE existing activity by ID and exact name. Requires separate user confirmation. For daily/weekly activities this removes the entire recurring record, not one occurrence. Never delete by a guessed ID/name or delete all.",
        arguments_model=DeleteActivityArguments,
    ))
    registry.register(Tool(
        name="edit_activity",
        description="Propose editing ONE existing activity by current ID and exact name, with one or more field changes. Requires separate confirmation. Edits a recurring activity as a whole, not one occurrence. Never edit IDs, source, external IDs, active date ranges or exams. Changing recurrence must supply its required date/weekday.",
        arguments_model=EditActivityArguments,
    ))
    return registry
