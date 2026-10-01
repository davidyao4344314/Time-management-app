"""Shared-contract compatibility and dependency tests; no live API calls."""

import subprocess
import sys
import unittest
from pathlib import Path
from textwrap import dedent

from pydantic import ValidationError

from backend.app import (
    ai_archive_category_review, ai_archive_llm_classifier,
    ai_archive_summary, ai_proposal,
)
from backend.app.actions import contracts as actions
from backend.app.agent import contracts as agent
from backend.app.memory import contracts as memory


class SharedContractTests(unittest.TestCase):
    def test_original_imports_reexport_the_same_contracts(self):
        aliases = (
            (ai_proposal, actions, "AddActivityArguments"),
            (ai_proposal, actions, "AddActivityAction"),
            (ai_proposal, actions, "WEEKDAYS"),
            (ai_proposal, memory, "MemoryRequest"),
            (ai_proposal, agent, "AgentProposal"),
            (ai_proposal, agent, "InvalidProposalError"),
            (ai_proposal, agent, "validate_agent_proposal"),
            (ai_archive_llm_classifier, memory, "ArchiveCandidateDecision"),
            (ai_archive_llm_classifier, memory, "ArchiveClassificationBatch"),
            (ai_archive_llm_classifier, memory, "PROTECTED_CATEGORIES"),
            (ai_archive_llm_classifier, memory, "COMPACTABLE_CATEGORIES"),
            (ai_archive_summary, memory, "ArchiveCategorySummary"),
            (ai_archive_summary, memory, "ArchiveCategorizedSummary"),
            (ai_archive_summary, memory, "BASE_ARCHIVE_CATEGORIES"),
            (ai_archive_category_review, memory, "ArchiveCategoryProposal"),
        )
        for original, shared, name in aliases:
            with self.subTest(name=name):
                self.assertIs(getattr(original, name), getattr(shared, name))

    def test_proposal_composes_action_and_memory_contracts_without_changing_shape(self):
        proposal = {
            "message": "This is only a proposed study session.",
            "actions": [{
                "tool": "add_activity",
                "arguments": {
                    "name": "COMPSCI revision", "category": "Study",
                    "subject": "COMPSCI 130", "activity_type": "one_time",
                    "date": "2026-10-01", "weekday": None,
                    "start_time": "18:00", "end_time": "19:00",
                },
            }],
            "memory_request": {
                "time_reference": "last_week", "search_terms": ["COMPSCI"],
            },
        }
        parsed = agent.validate_agent_proposal(proposal)
        self.assertIsInstance(parsed.actions[0], actions.AddActivityAction)
        self.assertIsInstance(parsed.actions[0].arguments, actions.AddActivityArguments)
        self.assertIsInstance(parsed.memory_request, memory.MemoryRequest)
        self.assertEqual(parsed.model_dump(), proposal)
        self.assertEqual(
            agent.validate_agent_proposal({"message": "No changes needed.", "actions": []}).model_dump(),
            {"message": "No changes needed.", "actions": [], "memory_request": None},
        )

    def test_invalid_tools_and_memory_requests_still_fail_validation(self):
        with self.assertRaises(agent.InvalidProposalError):
            agent.validate_agent_proposal({
                "message": "Invalid action.",
                "actions": [{"tool": "delete_activity", "arguments": {}}],
            })
        for request in (
            {"time_reference": "tomorrow", "search_terms": []},
            {"time_reference": None, "search_terms": ["the"]},
            {"time_reference": None, "search_terms": ["COMPSCI"] * 6},
            {"time_reference": None, "search_terms": [], "extra": True},
        ):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                memory.MemoryRequest.model_validate(request)

    def _assert_isolated_import(self, code):
        result = subprocess.run(
            [sys.executable, "-B", "-c", dedent(code)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_contracts_import_without_agent_storage_or_openai(self):
        self._assert_isolated_import("""
            import sys
            sys.modules["openai"] = None
            sys.modules["sqlite3"] = None
            from backend.app.actions.contracts import AddActivityArguments
            from backend.app.agent.contracts import AgentProposal
            from backend.app.memory.contracts import MemoryRequest, ArchiveCategorySummary
            assert AgentProposal.model_validate({"message": "Hello", "actions": []}).memory_request is None
            for name in (
                "backend.app.ai_proposal", "backend.app.ai_memory",
                "backend.app.ai_config", "backend.app.ai_archive_summary",
                "backend.app.ai_archive_llm_classifier", "backend.app.ai_archive_category_review",
                "backend.app.ai_archive_persistence", "backend.app.ai_durable_memory",
            ):
                assert name not in sys.modules, name
        """)

    def test_archive_search_no_longer_imports_main_agent(self):
        self._assert_isolated_import("""
            import sys
            sys.modules["openai"] = None
            sys.modules["sqlite3"] = None
            from backend.app.ai_archive_search import MemoryRequest
            from backend.app.memory.contracts import MemoryRequest as SharedMemoryRequest
            assert MemoryRequest is SharedMemoryRequest
            for name in (
                "backend.app.ai_proposal", "backend.app.ai_routing_pipeline",
                "backend.app.activity_observation", "backend.app.exam_observation",
            ):
                assert name not in sys.modules, name
        """)


if __name__ == "__main__":
    unittest.main()
