"""
this function gets the clomun the table and put it into an list got columns
"""
def get_clomuns(connection, table_name):
    # send an requrest to sql for information and store it in cursor
    cursor = connection.execute(f"PRAGMA table_info({table_name})")
    # get all rows by pagrama table info and put them all in an tuple list
    table_data = cursor.fetchall()

    columns = []
    # for loop to add everything from the table to
    for column in table_data:
        comumn_name = column[1]

        if comumn_name != "id":
            columns.append(comumn_name)
    return columns
"""
This function get user input base on how much cloumn name in cloumns and put the input in somthing called values
"""
def get_user_values(columns):
    values = []
    # repeating asking for values base the number of columns
    for column in columns:
        user_value = input(f"Enter {column}: ").strip()

        if user_value.lower() == "quit":
            return None

        values.append(user_value)

    return values
def add_activity(connection, values):
    if values is not None:
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

"""
print all the activities in the database
"""
def print_all_activities(connection):
    # this take every line in from the activities table  select all coluns
    cursor = connection.execute("SELECT * FROM activities")
    # take all rows from curosor and store them
    activities = cursor.fetchall()
    # print all activities.
    for activity in activities:
        print(f"ID: {activity[0]}")
        print(f"Name: {activity[1]}")
        print(f"Category: {activity[2]}")
        print(f"Subject: {activity[3]}")
        print(f"Date: {activity[4]}")
        print(f"Start time: {activity[5]}")
        print(f"End time: {activity[6]}")
        print()


def search_activity(connection, value_name):
    cursor = connection.execute("SELECT * FROM activities where name = ?", (value_name,))
    results = cursor.fetchall()
    if results != []:
        for activity in results:
            print("\n----------------------")
            print("Activity found")
            print("----------------------")
            print(f"ID: {activity[0]}")
            print(f"Name: {activity[1]}")
            print(f"Category: {activity[2]}")
            print(f"Subject: {activity[3]}")
            print(f"Date: {activity[4]}")
            print(f"Start time: {activity[5]}")
            print(f"End time: {activity[6]}")
            print("----------------------")
            return activity[0]
    else:
        print(f"No activity found for {value_name}")

def delete_activity(connection, activity_id):
    connection.execute(
        "DELETE FROM activities WHERE id = ?",
        (activity_id,)
    )

    connection.commit()

def edit_activity(connection, activity_id, column_name, new_value):
    sql = f"""
        UPDATE activities
        SET {column_name} = ?
        WHERE id = ?
    """

    connection.execute(sql, (new_value, activity_id))
    connection.commit()



