"""One HTTP composition root for chat proposals and explicit user approval."""

from contextlib import contextmanager

from backend.app.api import common
from backend.app.ai.actions.activity_tool import create_activity_tool_registry
from backend.app.ai.actions.execution import ActionExecutor
from backend.app.ai.actions.persistent_service import PersistentActionProposalService
from backend.app.conversations.service import open_store


@contextmanager
def execution_resources(approval, *, connection=None):
    # Only the explicit confirmation path opens a writable planner connection.
    owns_connection = connection is None
    if owns_connection:
        connection = common.create_connection()
    try:
        yield ActionExecutor(create_activity_tool_registry(connection, transactional=not owns_connection), approval)
    finally:
        if owns_connection:
            connection.close()


service = PersistentActionProposalService(open_store, execution_resources)
