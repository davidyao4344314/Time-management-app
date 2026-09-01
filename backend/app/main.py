from backend.app.database import create_connection, create_tables
from backend.app.activities import print_all_activities , search_activity, get_user_values, get_clomuns,add_activity,delete_activity, edit_activity,get_activity_schedule, search_by_id
from backend.app.calender import get_current_date, get_current_time ,print_all_dailies, get_current_day,get_todays_activities, check_activity_current
conection =create_connection()
create_tables(conection)


current_activity = []

while True:
    date = get_current_date()
    time = get_current_time()

    activities_today = get_todays_activities(conection)
    current_activity = check_activity_current(
        activities_today,
        time
    )

    print(f"current is {current_activity}")
    current_activities = check_activity_current(
        activities_today,
        time
    )
    print(f"current is {current_activities}")
    print("""
    1. Add activity
    2. View activities
    3. Delete activity
    4. Quit
    """)
    user_choice = input("Please enter your choice: ")
    #add activites
    if user_choice == "1":
        columns =get_clomuns(conection, "activities")
        values=get_user_values(columns)
        add_activity(conection,columns ,values )
    # print everything
    elif user_choice == "2":
        print_all_activities(conection)
    elif user_choice == "3":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
        delete_activity(conection, target_id)
    # delte by name
    elif user_choice == "4":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
    # search
    elif user_choice == "5":
        user_input_name = input("Please input the thing you want to delte")
        target_id=search_activity(conection, user_input_name)
        columns_name = input("Which field do you want to edit? ")
        new_values= input("Please input the new value")
        edit_activity(conection, target_id, columns_name, new_values)

    # delte everything
    elif user_choice == "6":
        conection.execute("DELETE FROM activities")
        conection.execute("DELETE FROM sqlite_sequence WHERE name = 'activities'")
        conection.commit()
    # search by id
    elif user_choice == "7":
        print_all_dailies(conection, activities_today)

    elif user_choice == "8":
        user_input_name = input("Please input the thing you want to delte")
        target_id = search_by_id(conection, user_input_name)
    elif user_choice == "9":

        user_input_name = input("Please input the thing you want to delte")
    elif user_choice == "q":
        break








