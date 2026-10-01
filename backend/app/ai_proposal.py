"""Compatibility facade; agent coordination and reasoning now have separate owners."""

from backend.app.infrastructure.module_compat import forward_module
from backend.app.agent import contracts as agent_contracts, reasoning, service
from backend.app.actions import contracts as action_contracts
from backend.app.memory import contracts as memory_contracts

forward_module(__name__, {
    "STUDY_PLANNING_INSTRUCTIONS": (reasoning, "STUDY_PLANNING_INSTRUCTIONS"),
    "get_max_recent_turns": (reasoning, "get_max_recent_turns"),
    "json": (reasoning, "json"),
    "get_agent_proposal": (service, "get_agent_proposal"),
    "PROPOSAL_MODEL": (service, "PROPOSAL_MODEL"),
    "os": (service, "os"),
    "OpenAI": (service, "OpenAI"),
    "is_openai_api_key_configured": (service, "is_openai_api_key_configured"),
    "get_agent_model_settings": (service, "get_agent_model_settings"),
    "select_agent_context": (service, "select_agent_context"),
    "collect_agent_observations": (service, "collect_agent_observations"),
    "build_activity_observation": (service, "build_activity_observation"),
    "build_exam_observation": (service, "build_exam_observation"),
    "AgentProposal": (agent_contracts, "AgentProposal"),
    "InvalidProposalError": (agent_contracts, "InvalidProposalError"),
    "validate_agent_proposal": (agent_contracts, "validate_agent_proposal"),
    "AddActivityAction": (action_contracts, "AddActivityAction"),
    "AddActivityArguments": (action_contracts, "AddActivityArguments"),
    "WEEKDAYS": (action_contracts, "WEEKDAYS"),
    "MemoryRequest": (memory_contracts, "MemoryRequest"),
})
