from datetime import datetime

def get_current_date():
    now = datetime.now()
    current_date = now.date()
    print(current_date)
    return current_date

def get_current_time():
    now = datetime.now()
    current_time = now.time()
    print(current_time)
    return current_time

