"""Regression checks for module moves; no real data or network access."""
import importlib
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from backend.tests.paths import BACKEND_DIRECTORY, PROJECT_DIRECTORY


class FolderLayoutTests(unittest.TestCase):
    def test_legacy_modules_share_canonical_implementations(self):
        pairs = (
            ("activities", "planner.activities"),
            ("activity_service", "planner.activity_service"),
            ("exams", "planner.exams"),
            ("calender", "planner.calendar"),
            ("canvas_import", "integrations.canvas_import"),
            ("uoa_timetable_import", "integrations.uoa_timetable_import"),
            ("ical_import", "integrations.ical_import"),
            ("ai_config", "ai.config"),
            ("agent.service", "ai.agent.service"),
            ("context.selection", "ai.context.selection"),
            ("observations.activities", "ai.observations.activities"),
            ("memory.recent", "ai.memory.recent"),
            ("actions.contracts", "ai.actions.contracts"),
        )
        for old, new in pairs:
            with self.subTest(old=old):
                self.assertIs(importlib.import_module("backend.app." + old),
                              importlib.import_module("backend.app." + new))

    def test_data_and_configuration_paths_have_not_moved(self):
        from backend.app import database
        from backend.app.ai import config
        from backend.app.ai.memory import paths
        from backend.app.infrastructure.paths import (
            BACKEND_DIRECTORY as backend_path,
            PROJECT_DIRECTORY as project_path,
        )
        from backend.app.integrations import canvas_import, uoa_timetable_import

        self.assertEqual(backend_path, BACKEND_DIRECTORY)
        self.assertEqual(project_path, PROJECT_DIRECTORY)
        self.assertEqual(database.db_file, BACKEND_DIRECTORY / "study_app.db")
        self.assertEqual(database.sql_file, PROJECT_DIRECTORY / "activities.sql")
        self.assertEqual(config.AI_ENV_FILE, PROJECT_DIRECTORY / ".env")
        self.assertEqual(canvas_import.CANVAS_ENV_FILE, PROJECT_DIRECTORY / ".env")
        self.assertEqual(uoa_timetable_import.UOA_ENV_FILE, PROJECT_DIRECTORY / ".env")
        self.assertEqual(paths.ARCHIVE_FILE, BACKEND_DIRECTORY / "ai_memory_archive.jsonl")
        self.assertEqual(paths.DURABLE_MEMORY_FILE, BACKEND_DIRECTORY / "ai_durable_memories.json")

    def test_server_entry_points_share_one_application(self):
        from backend import fastapi_test
        from backend.app.server import app
        self.assertIs(fastapi_test.app, app)
        expected_paths = ["/activities","/activities/all","/activities/current","/activities/current-next","/activities/remove-duplicates","/activities/search","/activities/today","/activities/week","/activities/{activity_id}","/activities/{activity_id}/move","/ai/config","/ai/config/status","/ai/memory-config","/ai/model-config","/ai/propose","/ai/test-observation","/canvas/import","/canvas/status","/exams","/exams/search","/exams/{exam_id}","/uoa/import","/uoa/status"]
        self.assertEqual(set(app.openapi()["paths"]), set(expected_paths) | {
            '/conversations', '/conversations/{conversation_id}/messages',
            '/conversations/{conversation_id}/settings', '/conversations/{conversation_id}/memory/export',
            '/conversations/{conversation_id}/summary'})
        self.assertIn('/conversations/{conversation_id}/summary', app.openapi()['paths'])
        route_pairs = [(route.path, tuple(sorted(route.methods)))
                       for route in app.routes if hasattr(route, "methods")]
        self.assertEqual(len(route_pairs), len(set(route_pairs)))
        for route in app.routes:
            if getattr(route, "path", "") in app.openapi()["paths"]:
                self.assertTrue(route.endpoint.__module__.startswith("backend.app.api."))

    def test_legacy_connection_patch_reaches_feature_routers(self):
        from backend import fastapi_test
        from backend.app.api import activities, calendar, common, exams
        connection = Mock()
        with patch.object(fastapi_test, "create_connection", return_value=connection) as connect:
            self.assertIs(common.create_connection, connect)
            with patch.object(activities, "get_all_activities", return_value=[]), \
                 patch.object(calendar, "get_todays_activities", return_value=[]), \
                 patch.object(exams, "get_all_exams", return_value=[]):
                self.assertEqual(activities.all_activities(), [])
                self.assertEqual(calendar.todays_activities(), [])
                self.assertEqual(exams.all_exams(), [])
        self.assertEqual(connect.call_count, 3)
        self.assertEqual(connection.close.call_count, 3)

    def test_cli_import_does_not_start_interactive_program(self):
        code = """
from unittest.mock import patch
from backend.app import database
with patch.object(database, 'create_connection', side_effect=AssertionError('DB opened')), \
     patch('builtins.input', side_effect=AssertionError('interactive prompt')):
    from backend.app import cli, main
    assert callable(cli.main)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=PROJECT_DIRECTORY,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_importer_help_commands_remain_safe_and_available(self):
        for filename in ("backend/app/uoa_timetable_import.py",
                         "backend/app/integrations/uoa_timetable_import.py"):
            with self.subTest(filename=filename):
                result = subprocess.run([sys.executable, "-B", filename, "--help"],
                                        cwd=PROJECT_DIRECTORY, capture_output=True,
                                        text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--save", result.stdout)


if __name__ == "__main__":
    unittest.main()
