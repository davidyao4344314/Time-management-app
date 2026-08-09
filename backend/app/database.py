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


def create_connection():
    """
    Open the SQLite database and return the connection.

    If study_app.db does not exist, SQLite creates it.
    If it already exists, SQLite opens it.
    """

    connection = sqlite3.connect(db_file)

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