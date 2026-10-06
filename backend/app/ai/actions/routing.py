"""Route validated agent output into pending proposals, never execution."""

from collections.abc import Mapping

from pydantic import ValidationError

from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import (
    ActionLayerError, ActionProposal, ActionRoute, ActionRoutingResult, ToolActionRequest,
)
from backend.app.ai.actions.registry import ToolRegistry


def route_agent_output(output: Mapping, registry: ToolRegistry, approval: ApprovalBoundary, *,
                       response_plan_requested: bool = False) -> ActionRoutingResult:
    """Accept today's {message, actions, ...} without changing its LLM/API schema.

    response_plan_requested is a reserved backend switch, not a new model field.
    The planner is never called here.
    """
    if not isinstance(output, Mapping) or not isinstance(output.get("actions"), list):
        raise ActionLayerError("Agent output must contain an actions list.")
    if type(response_plan_requested) is not bool:
        raise ActionLayerError("The response-plan route must be explicitly selected.")
    actions = output["actions"]
    if response_plan_requested and actions:
        raise ActionLayerError("Choose either tool actions or response planning.")
    if not actions:
        return ActionRoutingResult(
            route=ActionRoute.RESPONSE_PLAN if response_plan_requested else ActionRoute.NONE,
        )

    proposals = []
    for action in actions:
        try:
            request = ToolActionRequest.model_validate(action)
        except ValidationError:
            raise ActionLayerError("The proposed tool request is invalid.") from None
        tool = registry.resolve(request.tool)
        arguments = tool.validate(request.arguments)
        description = "\n".join(
            f"{name.replace('_', ' ').capitalize()}: {value}"
            for name, value in arguments.items() if value is not None
        )
        proposals.append(ActionProposal(
            tool_name=tool.name, arguments=arguments,
            display_title=tool.name.replace("_", " ").title(),
            display_description=description,
        ))

    # Validate the whole batch before registering any pending proposals.
    for proposal in proposals:
        approval.register(proposal)
    return ActionRoutingResult(route=ActionRoute.TOOL_ACTION, proposals=proposals)
