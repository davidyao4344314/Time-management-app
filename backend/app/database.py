import sqlite3
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


def add_activity_date_ranges(connection):
    """Append optional range fields without changing existing rows or indexes."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(activities)")}
    if not columns:
        return
    with connection:
        for name in ("active_start_date", "active_end_date"):
            if name not in columns:
                connection.execute(f"ALTER TABLE activities ADD COLUMN {name} TEXT")


def times_are_required(connection, table_name):
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()

    return any(
        column[1] in {"start_time", "end_time"} and column[3] == 1
        for column in columns
    )


def allow_null_times(connection):
    table_migrations = {
        "activities": {
            "columns": (
                "id, name, category, subject, activity_type, date, weekday, "
                "start_time, end_time, active_start_date, active_end_date"
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
                    active_end_date TEXT
                )
            """,
        },
        "exams": {
            "columns": (
                "id, name, category, subject, date, start_time, end_time"
            ),
            "create_sql": """
                CREATE TABLE exams_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subject TEXT,
                    date TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT
                )
            """,
        },
    }

    for table_name, migration in table_migrations.items():
        if not times_are_required(connection, table_name):
            continue

        new_table_name = f"{table_name}_new"
        columns = migration["columns"]

        with connection:
            connection.execute(migration["create_sql"])
            connection.execute(
                f"INSERT INTO {new_table_name} ({columns}) "
                f"SELECT {columns} FROM {table_name}"
            )
            connection.execute(f"DROP TABLE {table_name}")
            connection.execute(
                f"ALTER TABLE {new_table_name} RENAME TO {table_name}"
            )


def create_connection():
    """
    Open the SQLite database and return the connection.

    If study_app.db does not exist, SQLite creates it.
    If it already exists, SQLite opens it.
    """

    connection = sqlite3.connect(db_file)
    add_activity_date_ranges(connection)
    allow_null_times(connection)

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
