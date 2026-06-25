import sqlite3
from pathlib import Path

project_dir = Path(__file__).resolve().parents[2]
backend_dir = Path(__file__).resolve().parent.parent
sql_file = project_dir / "activities.sql"
db_file = backend_dir / "study_app.db"

connection = sqlite3.connect(db_file)

with open(sql_file, "r") as file:
    sql_code = file.read()

connection.executescript(sql_code)

connection.commit()
connection.close()

print("Database and activities table created.")
