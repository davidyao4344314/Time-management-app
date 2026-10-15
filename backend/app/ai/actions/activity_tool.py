"""Activity tool adapters: planner services own validation and database operations."""

from backend.app.ai.actions.contracts import AddActivityArguments, DeleteActivityArguments, EditActivityArguments
from backend.app.ai.actions.registry import ToolRegistry
from backend.app.ai.actions.tools import Tool, ToolPreconditionError
from backend.app.planner import activity_service


def _review_check(connection, arguments, snapshot):
    try:
        activity_service.verify_activity_snapshot(connection, arguments["activity_id"], arguments["expected_name"], snapshot)
    except activity_service.ActivityValidationError as error:
        raise ToolPreconditionError(error.detail) from None


class AddActivityTool(Tool):
    """Use the caller's connection and existing creation service, not direct SQL.

    The caller owns connection lifetime. Invoke through ActionExecutor so the
    authoritative approval boundary gates creation, as with every trusted tool.
    """

    def __init__(self, connection, *, transactional=False):
        def create_activity(arguments):
            prepared = activity_service.prepare_new_activity(arguments)
            created = activity_service.create_activity_record(connection, prepared,
                **({"commit": False} if transactional else {}))
            return {"activity_id": created[0]}

        super().__init__(
            name="add_activity",
            description="Create an activity after explicit user approval.",
            arguments_model=AddActivityArguments,
            handler=create_activity,
        )


class DeleteActivityTool(Tool):
    """Delete one checked record, only through the existing approval executor."""

    def __init__(self, connection, *, transactional=False):
        def verify(arguments):
            try:
                activity_service.prepare_activity_deletion(connection, **arguments)
            except activity_service.ActivityValidationError as error:
                raise ToolPreconditionError(error.detail) from None

        def remove(arguments):
            return activity_service.delete_activity_record(connection, **arguments)

        super().__init__(name="delete_activity", description="Delete one activity after explicit user approval.",
                         arguments_model=DeleteActivityArguments, handler=remove, preflight=verify,
                         review_validator=lambda args, snapshot: _review_check(connection, args, snapshot),
                         reviewed_handler=lambda args, snapshot: activity_service.delete_activity_record(
                             connection, **args, expected_snapshot=snapshot, commit=not transactional))


class EditActivityTool(Tool):
    """Review/validate read-only, then atomically update the same activity ID."""

    def __init__(self, connection, *, transactional=False):
        def verify(arguments):
            try:
                activity_service.prepare_activity_update(connection, **arguments)
            except activity_service.ActivityValidationError as error:
                raise ToolPreconditionError(error.detail) from None

        def update(arguments):
            return activity_service.update_activity_fields(connection, **arguments)

        super().__init__(name="edit_activity", description="Edit one activity after explicit user approval.",
                         arguments_model=EditActivityArguments, handler=update, preflight=verify,
                         review_validator=lambda args, snapshot: _review_check(connection, args, snapshot),
                         reviewed_handler=lambda args, snapshot: activity_service.update_activity_fields(
                             connection, **args, expected_snapshot=snapshot, commit=not transactional))


def describe_activity_proposals(connection, proposals):
    """Build edit/delete review cards from fresh read-only database data."""
    reviewed = []
    for proposal in proposals:
        if proposal.tool_name == "add_activity":
            conflicts = activity_service.check_activity_conflicts(connection, proposal.arguments)
            description = proposal.display_description
            if conflicts:
                description += "\nWarning: overlaps existing activities (you may still confirm):"
                for item in conflicts[:10]:
                    description += f"\n{item['name']} — {item['date']} {item['start_time']}–{item['end_time']}"
                if len(conflicts) > 10:
                    description += f"\nAnd {len(conflicts) - 10} more conflicts."
            if proposal.arguments["activity_type"] != "one_time":
                description += "\nRecurring activity: availability context checks near-term dates, not every future occurrence."
            reviewed.append(proposal.model_copy(update={"display_description": description}))
            continue
        if proposal.tool_name not in {"delete_activity", "edit_activity"}:
            reviewed.append(proposal)
            continue
        if proposal.tool_name == "edit_activity":
            target, updates = activity_service.prepare_activity_update(connection, **proposal.arguments)
        else:
            target = activity_service.prepare_activity_deletion(connection, **proposal.arguments)
        description = "\n".join(f"{field.replace('_', ' ').capitalize()}: {value}"
                                 for field, value in target.items() if value is not None and field != "external_id")
        if proposal.tool_name == "edit_activity":
            description += "\nProposed changes:"
            for field, value in updates.items():
                before = target[field] if target[field] is not None else "Not set"
                after = value if value is not None else "Not set"
                description += f"\n{field.replace('_', ' ').capitalize()}: {before} → {after}"
            description += "\nUpdate the existing activity in place; its ID and import metadata are preserved."
            if target["activity_type"] in {"daily", "weekly"} or updates.get("activity_type") in {"daily", "weekly"}:
                description += "\nThis edits the recurring activity as a whole, not just one calendar occurrence."
            if target.get("source") in {"Canvas", "UoA"}:
                description += "\nOnly the local activity changes; the source feed and external identifiers are unchanged."
        else:
            description += "\nPermanently delete this activity. This cannot be undone in the app."
            if target["activity_type"] in {"daily", "weekly"}:
                description += "\nThis deletes the entire recurring activity, not just one calendar occurrence."
            if target.get("source") in {"Canvas", "UoA"}:
                description += "\nOnly the local record is removed; the source feed is unchanged and a later import may restore it."
        reviewed.append(proposal.model_copy(update={"display_description": description, "target_snapshot": target}))
    return reviewed


def create_activity_tool_registry(connection, *, transactional=False):
    """Opt into approved activity changes; public schemas still have no handlers."""
    registry = ToolRegistry()
    registry.register(AddActivityTool(connection, transactional=transactional))
    registry.register(DeleteActivityTool(connection, transactional=transactional))
    registry.register(EditActivityTool(connection, transactional=transactional))
    return registry
