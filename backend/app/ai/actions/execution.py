"""Execute only a trusted approved proposal ID; no real planner tools yet."""

from backend.app.ai.actions.approval import ApprovalBoundary
from backend.app.ai.actions.contracts import ActionLayerError, ActionResult
from backend.app.ai.actions.registry import ToolRegistry, UnknownToolError
from backend.app.ai.actions.tools import InvalidToolArgumentsError, ToolExecutionUnavailableError


class ActionExecutor:
    def __init__(self, registry: ToolRegistry, approval: ApprovalBoundary):
        self.registry = registry
        self.approval = approval

    def execute(self, proposal_id: str) -> ActionResult:
        # Resolve authoritative backend state, NOT an LLM/browser proposal object.
        try:
            proposal = self.approval.begin_execution(proposal_id)
        except ActionLayerError as error:
            return self._failure(proposal_id, str(error))

        try:
            tool = self.registry.resolve(proposal.tool_name)
            result = ActionResult(
                proposal_id=proposal.id, success=True,
                result=tool.execute(proposal.arguments),
                message=f"{proposal.display_title} completed.",
            )
        except UnknownToolError:
            result = self._failure(proposal.id, "The requested tool is not registered.")
        except InvalidToolArgumentsError:
            result = self._failure(proposal.id, "The tool arguments are invalid.")
        except ToolExecutionUnavailableError:
            result = self._failure(proposal.id, "Execution is not available for this tool.")
        except Exception:
            # The handler may have changed state before raising, or its return
            # value may have failed result validation. Neither proves rollback.
            # Do not expose tool internals, arguments, SQL or raw exception text.
            result = ActionResult(
                proposal_id=proposal.id, success=False,
                error="The tool outcome could not be confirmed.",
                message="The action's outcome is unconfirmed. Check the app before trying again.",
            )

        self.approval.finish_execution(result)
        return result

    @staticmethod
    def _failure(proposal_id, error):
        return ActionResult(
            proposal_id=proposal_id, success=False, error=error,
            message="This execution attempt did not run the action.",
        )
