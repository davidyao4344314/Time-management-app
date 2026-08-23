import sqlite3
from pathlib import Path

from backend.app import activities
from backend.app.database import create_connection, create_tables
from backend.app.activities import print_all_activities , search_activity, get_user_values, get_clomuns,add_activity,delete_activity, edit_activity,get_activity_schedule
from backend.app.calender import get_current_date, get_current_time
conection =create_connection()
create_tables(conection)


while True:
    date = get_current_date()
    time = get_current_time()

    actvities_today = []

    activity_id = 1

    while True:
        schedule = get_activity_schedule(conection, activity_id)

        if schedule is None:
            break

        print(schedule)
        if str(date) == schedule[0]:
            actvities_today.append(activity_id)

        activity_id += 1
    print(actvities_today)

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
        add_activity(conection,columns ,values )
    elif user_choice == "2":
        print_all_activities(conection)
    elif user_choice == "3":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
        delete_activity(conection, target_id)
    elif user_choice == "4":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
    elif user_choice == "5":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
        columns_name = input("Which field do you want to edit? ")
        new_values= input("Please input the new value")
        edit_activity(conection, target_id, columns_name, new_values)


    elif user_choice == "6":
        conection.execute("DELETE FROM activities")
        conection.execute("DELETE FROM sqlite_sequence WHERE name = 'activities'")
        conection.commit()
    elif user_choice == "q":
        break








