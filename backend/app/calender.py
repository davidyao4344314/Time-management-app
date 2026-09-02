from datetime import datetime, timedelta
from backend.app.activities import get_activity_schedule, get_activity_name_by_id, get_all_activities


def get_current_date():
    now = datetime.now()
    current_date = now.date()
    return current_date

def get_current_time():
    now = datetime.now()
    current_time = now.time().strftime("%H:%M")
    return current_time

def get_current_day():
    return datetime.now().strftime("%A")

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

def get_current_week():
    today = get_current_date()

    monday = today - timedelta(days=today.weekday())

    week = []

    for i in range(7):
        day = monday + timedelta(days=i)
        week.append(day)

    return week
def is_activity_on_date(
    activity_type,
    activity_date,
    activity_day,
    chosen_date
):
    if not isinstance(activity_type, str):
        return False

    activity_type = activity_type.strip().lower()

    if activity_type == "one_time":
        if not isinstance(activity_date, str):
            return False

        try:
            stored_date = datetime.strptime(
                activity_date.strip(),
                "%Y-%m-%d",
            ).date()
        except ValueError:
            return False

        return stored_date == chosen_date

    elif activity_type == "daily":
        return True

    elif activity_type == "weekly":
        if not isinstance(activity_day, str):
            return False

        valid_weekdays = {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        }
        stored_weekday = activity_day.strip().lower()

        if stored_weekday not in valid_weekdays:
            return False

        return stored_weekday == chosen_date.strftime("%A").lower()

    return False


def is_valid_activity_time(start_time, end_time):
    if not isinstance(start_time, str) or not isinstance(end_time, str):
        return False

    try:
        parsed_start = datetime.strptime(start_time.strip(), "%H:%M")
        parsed_end = datetime.strptime(end_time.strip(), "%H:%M")
    except ValueError:
        return False

    return parsed_start < parsed_end


def get_week_activities(connection):
    activities = get_all_activities(connection)
    current_week = get_current_week()
    week_activities = []

    for calendar_date in current_week:
        for activity in activities:
            if len(activity) < 7:
                continue

            activity_type = activity[2]
            stored_date = activity[3]
            stored_weekday = activity[4]
            start_time = activity[5]
            end_time = activity[6]

            if not is_valid_activity_time(start_time, end_time):
                continue

            if not is_activity_on_date(
                activity_type,
                stored_date,
                stored_weekday,
                calendar_date,
            ):
                continue

            week_activities.append({
                "id": activity[0],
                "name": activity[1],
                "activity_type": activity_type.strip().lower(),
                "calendar_date": str(calendar_date),
                "start_time": start_time.strip(),
                "end_time": end_time.strip(),
            })

    return sorted(
        week_activities,
        key=lambda activity: (
            activity["calendar_date"],
            activity["start_time"],
            activity["name"],
        ),
    )
