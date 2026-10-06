"""Activity tool adapters: planner services own validation and database operations."""

from backend.app.ai.actions.contracts import AddActivityArguments, DeleteActivityArguments
from backend.app.ai.actions.registry import ToolRegistry
from backend.app.ai.actions.tools import Tool, ToolPreconditionError
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


class DeleteActivityTool(Tool):
    """Delete one checked record, only through the existing approval executor."""

    def __init__(self, connection):
        def verify(arguments):
            try:
                activity_service.prepare_activity_deletion(connection, **arguments)
            except activity_service.ActivityValidationError as error:
                raise ToolPreconditionError(error.detail) from None

        def remove(arguments):
            return activity_service.delete_activity_record(connection, **arguments)

        super().__init__(name="delete_activity", description="Delete one activity after explicit user approval.",
                         arguments_model=DeleteActivityArguments, handler=remove, preflight=verify)


def describe_activity_proposals(connection, proposals):
    """Enrich destructive review cards from fresh read-only database data."""
    reviewed = []
    for proposal in proposals:
        if proposal.tool_name != "delete_activity":
            reviewed.append(proposal)
            continue
        target = activity_service.prepare_activity_deletion(connection, **proposal.arguments)
        description = "\n".join(f"{field.replace('_', ' ').capitalize()}: {value}"
                                 for field, value in target.items() if value is not None)
        description += "\nPermanently delete this activity. This cannot be undone in the app."
        if target["activity_type"] in {"daily", "weekly"}:
            description += "\nThis deletes the entire recurring activity, not just one calendar occurrence."
        if target.get("source") in {"Canvas", "UoA"}:
            description += "\nOnly the local record is removed; the source feed is unchanged and a later import may restore it."
        reviewed.append(proposal.model_copy(update={"display_description": description}))
    return reviewed


def create_activity_tool_registry(connection):
    """Opt into approved creation/deletion; public schemas still have no handlers."""
    registry = ToolRegistry()
    registry.register(AddActivityTool(connection))
    registry.register(DeleteActivityTool(connection))
    return registry
