import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import database
from backend.app.server import app


class DatabaseStartupTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "startup.db"
        self.enterContext(patch.object(database, "db_file", self.path))

    def test_connections_do_not_prepare_schema_and_api_startup_does(self):
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master").fetchall(), [])

        with TestClient(app) as client:
            self.assertEqual(client.get("/activities").json(), [])
            with closing(database.create_connection()) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone(), (7,))
                connection.execute("SELECT * FROM conversation_memory_exports")
                connection.execute("SELECT * FROM action_proposals")
        with patch.object(database, "_prepare_planner_schema", side_effect=AssertionError("already migrated")):
            with TestClient(app) as client:
                self.assertEqual(client.get("/exams").json(), [])

    def test_migration_failure_rolls_back_new_tables_and_version_markers(self):
        def failing_migration(connection, *, commit):
            self.assertFalse(commit)
            connection.execute("CREATE TABLE partial_schema (id INTEGER)")
            raise sqlite3.OperationalError("fixture migration failure")

        with self.assertRaises(sqlite3.OperationalError):
            database.initialize_database((("test_failure", failing_migration),))
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master").fetchall(), [])
        database.initialize_database()

    def test_legacy_time_migration_preserves_uoa_mappings_and_id_sequence(self):
        schema = database.sql_file.read_text().replace("start_time TEXT", "start_time TEXT NOT NULL")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript(schema)
            connection.execute("""INSERT INTO activities (id, name, category, activity_type, start_time)
                VALUES (20, 'Lab', 'University', 'weekly', '09:00'),
                       (30, 'Removed', 'Study', 'daily', '09:00')""")
            connection.execute("DELETE FROM activities WHERE id = 30")
            connection.execute("INSERT INTO uoa_activity_external_ids (activity_id, external_id) VALUES (20, 'uid')")

        database.initialize_database()
        with closing(database.create_connection()) as connection:
            self.assertEqual(connection.execute("SELECT activity_id, external_id FROM uoa_activity_external_ids").fetchall(),
                             [(20, "uid")])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            cursor = connection.execute("INSERT INTO activities (name, category, activity_type) VALUES ('Untimed', 'Study', 'daily')")
            self.assertEqual(cursor.lastrowid, 31)
