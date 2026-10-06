"""Static import boundaries and compatibility checks; no network or data writes."""

import ast
import unittest
from pathlib import Path
from backend.tests.paths import BACKEND_DIRECTORY, PROJECT_DIRECTORY


APP_DIRECTORY = BACKEND_DIRECTORY / "app"


def local_import_graph():
    sources = {}
    for path in APP_DIRECTORY.rglob("*.py"):
        suffix = path.relative_to(APP_DIRECTORY).with_suffix("").parts
        if suffix[-1] == "__init__":
            suffix = suffix[:-1]
        name = ".".join(("backend", "app", *suffix))
        sources[name] = ast.parse(path.read_text(), filename=str(path))
    graph = {name: set() for name in sources}
    for name, tree in sources.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                graph[name].update(alias.name for alias in node.names if alias.name in sources)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    if candidate in sources:
                        graph[name].add(candidate)
                    elif node.module in sources:
                        graph[name].add(node.module)
    return graph


class ArchitectureTests(unittest.TestCase):
    def test_local_import_graph_has_no_cycle(self):
        graph = local_import_graph()
        completed = set()

        def visit(module, trail):
            self.assertNotIn(module, trail, "Import cycle: " + " -> ".join((*trail, module)))
            if module in completed:
                return
            for dependency in graph[module]:
                visit(dependency, (*trail, module))
            completed.add(module)

        for module in graph:
            visit(module, ())

    def test_routing_observations_and_infrastructure_do_not_import_higher_layers(self):
        graph = local_import_graph()
        for module, dependencies in graph.items():
            allowed = set()
            if module.startswith("backend.app.ai.context."):
                if module == "backend.app.ai.context.contracts":
                    allowed = {"backend.app.ai.memory.contracts"}
                forbidden = ("backend.app.ai.observations", "backend.app.ai.agent", "backend.app.api",
                             "backend.app.ai.memory", "backend.app.planner.activities", "backend.app.planner.exams")
            elif module.startswith("backend.app.ai.observations."):
                if module == "backend.app.ai.observations.memory":
                    allowed = {"backend.app.ai.memory.search"}
                forbidden = ("backend.app.ai.agent", "backend.app.api", "backend.app.ai.memory",
                             "backend.app.ai.context", "backend.app.ai.compat")
            elif module.startswith("backend.app.ai.actions."):
                forbidden = ("backend.app.ai.agent", "backend.app.ai.context", "backend.app.ai.observations",
                             "backend.app.ai.memory", "backend.app.ai.compat", "backend.app.api",
                             "backend.app.planner", "backend.app.integrations", "backend.app.database")
            elif module.startswith("backend.app.infrastructure."):
                forbidden = ("backend.app.ai", "backend.app.api", "backend.app.planner",
                             "backend.app.integrations", "backend.app.screen_time")
            elif module.startswith(("backend.app.planner.", "backend.app.integrations.",
                                    "backend.app.screen_time.")):
                forbidden = ("backend.app.ai", "backend.app.api", "backend.app.server")
            elif module.startswith('backend.app.conversations.'):
                forbidden = ('backend.app.api', 'backend.app.server')
                if module.endswith(('.storage', '.contracts')):
                    forbidden += ('backend.app.ai', 'backend.app.planner',
                                  'backend.app.conversations.service', 'backend.app.conversations.summary',
                                  'backend.app.conversations.memory_export', 'backend.app.conversations.legacy')
            elif module == 'backend.app.database':
                forbidden = ('backend.app.conversations', 'backend.app.ai', 'backend.app.api')
            else:
                continue
            with self.subTest(module=module):
                self.assertFalse({dependency for dependency in dependencies
                                  if dependency.startswith(forbidden) and dependency not in allowed})

    def test_storage_and_planning_have_no_reverse_dependency(self):
        graph = local_import_graph()
        self.assertNotIn("backend.app.ai.memory.recent", graph["backend.app.ai.memory.archive_store"])
        self.assertNotIn("backend.app.ai.memory.selection", graph["backend.app.ai.memory.archive_store"])
        self.assertNotIn("backend.app.ai.memory.durable", graph["backend.app.ai.memory.durable_store"])
        self.assertNotIn("backend.app.ai.memory.compaction", graph["backend.app.ai.memory.compaction_plan"])
        self.assertFalse(any(dependency.startswith("backend.app.api")
                             for dependency in graph["backend.app.planner.activity_service"]))

    def test_conversation_orchestrators_do_not_embed_sql(self):
        for name in ('service', 'summary', 'memory_export', 'legacy', 'memory_context', 'context'):
            tree = ast.parse((APP_DIRECTORY / 'conversations' / f'{name}.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'execute', 'executemany', 'executescript'}:
                    # Connection setup is allowed; all business SQL belongs to storage.
                    self.assertTrue(node.args and isinstance(node.args[0], ast.Constant)
                                    and node.args[0].value == 'PRAGMA foreign_keys=ON', name)

    def test_legacy_imports_resolve_to_canonical_implementations(self):
        from backend.app import (
            activity_observation, ai_context_router, ai_durable_memory,
            ai_memory, ai_proposal, ai_routing_pipeline, exam_observation, memory_debug,
        )
        from backend.app.ai.agent import service
        from backend.app.ai.context import keywords, selection
        from backend.app.dev import memory_debug as debug
        from backend.app.ai.memory import contracts, durable, recent
        from backend.app.ai.observations import activities, exams

        self.assertIs(ai_memory.add_completed_turn, recent.add_completed_turn)
        self.assertIs(ai_durable_memory.extract_durable_memories, durable.extract_durable_memories)
        self.assertIs(ai_durable_memory.DurableMemoryStore, contracts.DurableMemoryStore)
        self.assertIs(ai_proposal.get_agent_proposal, service.get_agent_proposal)
        self.assertIs(ai_context_router, keywords)
        self.assertIs(ai_routing_pipeline, selection)
        self.assertIs(activity_observation, activities)
        self.assertIs(exam_observation, exams)
        self.assertIs(memory_debug, debug)


if __name__ == "__main__":
    unittest.main()
