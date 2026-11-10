import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path


# Find the backend folder.
# __file__ means the current Python file.
# .resolve() gets the full path.
# .parent.parent moves up two folders.
backend_dir = Path(__file__).resolve().parent.parent


# Find the main project folder.
# parents[2] moves up three levels from the current Python file.
project_dir = Path(__file__).resolve().parents[2]


# Create the path to the SQLite database file.
# The database will be stored inside the backend folder.
db_file = backend_dir / "study_app.db"


# Create the path to the SQL file.
# This file contains your CREATE TABLE statements.
sql_file = project_dir / "activities.sql"


def add_activity_date_ranges(connection, *, commit=True):
    """Append optional range fields without changing existing rows or indexes."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(activities)")}
    if not columns:
        return
    with (connection if commit else nullcontext()):
        for name in ("active_start_date", "active_end_date"):
            if name not in columns:
                connection.execute(f"ALTER TABLE activities ADD COLUMN {name} TEXT")


def add_record_sources(connection, *, commit=True):
    """Append source once, retaining every existing row and column position."""
    with (connection if commit else nullcontext()):
        for table in ("activities", "exams"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            if "source" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL DEFAULT 'Manual'")
                # These category values were written by the legacy converters.
                # Apply inference ONLY during migration, not to new Manual rows.
                connection.execute(f"UPDATE {table} SET source = 'Canvas' WHERE category = 'Canvas'")
                if table == "activities":
                    connection.execute("""
                        UPDATE activities SET source = 'UoA'
                        WHERE category = 'University' AND activity_type = 'weekly'
                          AND active_start_date IS NOT NULL AND active_end_date IS NOT NULL
                    """)
            else:
                connection.execute(f"UPDATE {table} SET source = 'Manual' WHERE source IS NULL OR trim(source) = ''")


def add_external_id_storage(connection, *, commit=True):
    """Keep old records intact; their new external_id remains NULL."""
    with (connection if commit else nullcontext()):
        for table in ("activities", "exams"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if columns and "external_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN external_id TEXT")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS uoa_activity_external_ids(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                external_id TEXT NOT NULL,
                FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                UNIQUE(activity_id, external_id)
            )
        """)


def times_are_required(connection, table_name):
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()

    return any(
        column[1] in {"start_time", "end_time"} and column[3] == 1
        for column in columns
    )


def allow_null_times(connection, *, commit=True):
    table_migrations = {
        "activities": {
            "columns": (
                "id, name, category, subject, activity_type, date, weekday, "
                "start_time, end_time, active_start_date, active_end_date, source, external_id"
            ),
            "create_sql": """
                CREATE TABLE activities_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subject TEXT,
                    activity_type TEXT NOT NULL
                        CHECK (activity_type IN ('one_time', 'daily', 'weekly')),
                    date TEXT,
                    weekday TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    active_start_date TEXT,
                    active_end_date TEXT,
                    source TEXT NOT NULL DEFAULT 'Manual',
                    external_id TEXT
                )
            """,
        },
        "exams": {
            "columns": (
                "id, name, category, subject, date, start_time, end_time, source, external_id"
            ),
            "create_sql": """
                CREATE TABLE exams_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subject TEXT,
                    date TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    source TEXT NOT NULL DEFAULT 'Manual',
                    external_id TEXT
                )
            """,
        },
    }

    for table_name, migration in table_migrations.items():
        if not times_are_required(connection, table_name):
            continue

        new_table_name = f"{table_name}_new"
        columns = migration["columns"]

        with (connection if commit else nullcontext()):
            connection.execute(migration["create_sql"])
            previous_sequence = connection.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = ?", (table_name,),
            ).fetchone()
            connection.execute(
                f"INSERT INTO {new_table_name} ({columns}) "
                f"SELECT {columns} FROM {table_name}"
            )
            connection.execute(f"DROP TABLE {table_name}")
            connection.execute(
                f"ALTER TABLE {new_table_name} RENAME TO {table_name}"
            )
            if previous_sequence is not None:
                connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))
                connection.execute(
                    "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                    (table_name, previous_sequence[0]),
                )


def add_screen_time_storage(connection, *, commit=True):
    """Create Screen Time storage in existing databases without changing their rows."""
    with (connection if commit else nullcontext()):
        connection.execute("""
            CREATE TABLE IF NOT EXISTS screen_time_daily(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                total_minutes INTEGER,
                productive_minutes INTEGER,
                social_minutes INTEGER,
                entertainment_minutes INTEGER,
                other_minutes INTEGER
            )
        """)


def _prepare_planner_schema(connection, *, commit=False):
    # executescript would commit the caller's transaction. The bootstrap SQL
    # file contains one complete CREATE statement at a time.
    statement = ""
    for line in sql_file.read_text().splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete planner schema statement.")
    add_activity_date_ranges(connection, commit=commit)
    add_record_sources(connection, commit=commit)
    add_external_id_storage(connection, commit=commit)
    allow_null_times(connection, commit=commit)
    add_screen_time_storage(connection, commit=commit)


def initialize_database(extra_migrations=()):
    """Apply versioned migrations once, before the app opens regular connections."""
    migrations = (("001_planner", _prepare_planner_schema), *extra_migrations)
    # Keep FK checks disabled only on this connection while legacy tables are
    # rebuilt, so SQLite does not cascade-delete existing UoA UID mappings.
    with closing(sqlite3.connect(db_file, timeout=10)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        applied = {name for (name,) in connection.execute("SELECT name FROM schema_migrations")}
        for name, migrate in migrations:
            if name not in applied:
                migrate(connection, commit=False)
                connection.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))


def create_connection(*, timeout=5):
    """Open a prepared database without running schema or data migrations."""
    connection = sqlite3.connect(db_file, timeout=timeout)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_tables(connection):
    """
    Read the SQL code from activities.sql
    and execute it inside the database.
    """

    # Open the SQL file in reading mode.
    with open(sql_file, "r") as file:

        # Read all SQL text from the file.
        sql_code = file.read()

    # Run all SQL statements found in the file.
    #
    # executescript() is useful because your SQL file
    # can contain multiple commands, such as:
    #
    # CREATE TABLE activities (...);
    # CREATE TABLE exams (...);
    connection.executescript(sql_code)

    # Save the database changes.
    connection.commit()
