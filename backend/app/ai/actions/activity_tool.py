"""Explicitly opted-in activity creation adapter; no HTTP or LLM wiring."""

from backend.app.ai.actions.contracts import AddActivityArguments
from backend.app.ai.actions.registry import ToolRegistry
from backend.app.ai.actions.tools import Tool
from backend.app.planner import activity_service


class AddActivityTool(Tool):
    """Use the caller's connection and existing creation service, not direct SQL.

    The caller owns connection lifetime. Invoke through ActionExecutor so the
    authoritative approval boundary gates creation, as with every trusted tool.
    """

    def __init__(self, connection):
        def create_activity(arguments):
            prepared = activity_service.prepare_new_activity(arguments)
            created = activity_service.create_activity_record(connection, prepared)
            return {"activity_id": created[0]}

        super().__init__(
            name="add_activity",
            description="Create an activity after explicit user approval.",
            arguments_model=AddActivityArguments,
            handler=create_activity,
        )


def create_activity_tool_registry(connection):
    """Opt into the real tool explicitly; the proposal-only default is unchanged."""
    registry = ToolRegistry()
    registry.register(AddActivityTool(connection))
    return registry
