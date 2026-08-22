import sqlite3
from pathlib import Path

from backend.app import activities
from backend.app.database import create_connection, create_tables
from backend.app.activities import print_all_activities , search_activity, get_user_values, get_clomuns,add_activity,delete_activity

conection =create_connection()
create_tables(conection)



while True:
    print("""
    1. Add activity
    2. View activities
    3. Delete activity
    4. Quit
    """)
    user_choice = input("Please enter your choice: ")
    if user_choice == "1":
        columns =get_clomuns(conection, "activities")
        values=get_user_values(columns)
        add_activity(conection,values )
    elif user_choice == "2":
        print_all_activities(conection)
    elif user_choice == "3":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
        delete_activity(conection, target_id)








