"""One HTTP composition root for chat proposals and explicit user approval."""

from contextlib import contextmanager

from backend.app.api import common
from backend.app.ai.actions.activity_tool import create_activity_tool_registry
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.service import ActionProposalService


@contextmanager
def execution_resources(approval):
    # Only the explicit confirmation path opens a writable planner connection.
    connection = common.create_connection()
    try:
        yield ActionExecutor(create_activity_tool_registry(connection), approval)
    finally:
        connection.close()


service = ActionProposalService(execution_resources)
