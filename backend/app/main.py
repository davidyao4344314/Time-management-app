import sqlite3
from pathlib import Path


def get_user_values(columns):
    values = []

    for column in columns:
        user_value = input(f"Enter {column}: ").strip()

        if user_value.lower() == "quit":
            return None

        values.append(user_value)

    return values

def get_clomuns(connection, table_name):
    cursor = connection.execute(f"PRAGMA table_info({table_name})")
    table_data = cursor.fetchall()

    columns = []
    for column in table_data:
        comumn_name = column[1]

        if comumn_name != "id":
            columns.append(comumn_name)

    return columns



project_dir = Path(__file__).resolve().parents[2]
backend_dir = Path(__file__).resolve().parent.parent

sql_file = project_dir / "activities.sql"
db_file = backend_dir / "study_app.db"

connection = sqlite3.connect(db_file)

with open(sql_file, "r") as file:
    sql_code = file.read()

connection.executescript(sql_code)

columns = [
    "name",
    "category",
    "subject",
    "date",
    "start_time",
    "end_time"
]

while True:
    columns = get_clomuns(connection, "activities")
    values = get_user_values(columns)

    if values is None:
        break

    connection.execute("""
        INSERT INTO activities (
            name,
            category,
            subject,
            date,
            start_time,
            end_time
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, values)

    connection.commit()

    print("Activity added successfully.\n")

connection.close()