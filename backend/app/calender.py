from datetime import datetime
from activities import get_activity_schedule, get_activity_name_by_id, get_all_activities

def get_current_date():
    now = datetime.now()
    current_date = now.date()
    #print(current_date)
    return current_date

def get_current_time():
    now = datetime.now()
    current_time = now.time().strftime("%H:%M")
    #print(current_time)
    return current_time

def get_current_day():
    return datetime.now().strftime("%A")
"""
def daily_activities(conection, date):
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
    return actvities_today
"""
def print_all_dailies(connection, activit_list):
    for activity in activit_list:
        print(f"ID: {activity[0]}")
        print(f"Name: {activity[1]}")
        print(f"Type: {activity[2]}")
        print(f"Date: {activity[3]}")
        print(f"Day: {activity[4]}")
        print(f"Start time: {activity[5]}")
        print(f"End time: {activity[6]}")


def is_activity_today(activity_type, activity_date, activity_day):
    today = str(get_current_date())
    current_day = get_current_day()

    if activity_type == "one_time":
        return activity_date == today

    elif activity_type == "daily":
        return True

    elif activity_type == "weekly":
        return activity_day == current_day

    return False

def get_todays_activities(connection):
    activities = get_all_activities(connection)

    activities_today = []

    for activity in activities:
        activity_type = activity[2]
        activity_date = activity[3]
        activity_day = activity[4]

        if is_activity_today(
            activity_type,
            activity_date,
            activity_day
        ):
            activities_today.append(activity)

    return activities_today

def check_activity_current(activities_today, current_time):
    current_activities = []

    for activity in activities_today:
        start_time = activity[5]
        end_time = activity[6]

        if start_time <= current_time < end_time:
            current_activities.append(activity[0])

    return current_activities