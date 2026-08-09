import sqlite3
from pathlib import Path

from backend.app.database import create_connection, create_tables
from backend.app.activities import print_all_activities

conection =create_connection()
create_tables(conection)
print_all_activities(conection)



while True:
    user_choice = input("Please enter your choice: ")
