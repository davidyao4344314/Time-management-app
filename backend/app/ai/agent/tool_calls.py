"""Translate Responses function calls into validated requests, never execution."""

import json

from backend.app.ai.actions.contracts import ActionLayerError, MAX_ADD_ACTIVITY_PROPOSALS
from backend.app.ai.actions.registry import create_proposal_tool_registry
from backend.app.ai.actions.routing import prepare_tool_proposals
from backend.app.ai.agent.contracts import InvalidProposalError


def public_agent_tools():
    """Expose schema-only contracts. No handlers, storage or approval authority."""
    return [{"type": "function", "name": item["name"],
             "description": item["description"], "parameters": item["input_schema"],
             "strict": True}
            for item in create_proposal_tool_registry().public_contracts()]


def normalize_tool_calls(response):
    """Validate a bounded all-add batch, or one edit/delete; never execute."""
    output = getattr(response, "output", [])
    if not isinstance(output, list):
        raise InvalidProposalError("The model returned invalid output items.")
    calls = [item for item in output
             if getattr(item, "type", None) == "function_call"]
    if len(calls) > MAX_ADD_ACTIVITY_PROPOSALS:
        raise InvalidProposalError("Too many activity proposals in one reply.")
    if len(calls) > 1 and any(getattr(call, "name", None) != "add_activity" for call in calls):
        raise InvalidProposalError("Only add_activity supports multiple proposals per reply.")
    requests = []
    call_ids, fingerprints = set(), set()
    for call in calls:
        # Function-call status is optional in the SDK. The enclosing response
        # must be completed (checked by the reasoner); reject explicit partials.
        if (getattr(call, "status", None) not in (None, "completed")
                or not isinstance(getattr(call, "call_id", None), str) or not call.call_id.strip()
                or not isinstance(getattr(call, "arguments", None), str)):
            raise InvalidProposalError("The model returned an incomplete tool request.")
        if call.call_id in call_ids:
            raise InvalidProposalError("The model returned a duplicated tool request.")
        call_ids.add(call.call_id)
        try:
            arguments = json.loads(call.arguments)
            proposals = prepare_tool_proposals(
                [{"tool": call.name, "arguments": arguments}], create_proposal_tool_registry(),
            )
        except (ValueError, TypeError, AttributeError, ActionLayerError):
            raise InvalidProposalError("The model returned an invalid tool request.") from None
        request = {"tool": proposals[0].tool_name, "arguments": proposals[0].arguments}
        fingerprint = json.dumps(request, sort_keys=True)
        if fingerprint in fingerprints:
            raise InvalidProposalError("The model returned a duplicated activity proposal.")
        fingerprints.add(fingerprint)
        requests.append(request)
    return requests
