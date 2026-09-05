def get_all_exams(connection):
    cursor = connection.execute("SELECT * FROM exams")
    return cursor.fetchall()

def add_exam(connection, columns, values):
    column_names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    sql = f"""
        INSERT INTO exams ({column_names})
        VALUES ({placeholders})
    """

    connection.execute(sql, values)
    connection.commit()

def delete_exam(connection, exam_id):
    connection.execute(
        "DELETE FROM exams WHERE id = ?",
        (exam_id,)
    )
    connection.commit()

def get_all_exams(connection):
    cursor = connection.execute(
        "SELECT * FROM exams"
    )

    return cursor.fetchall()


def add_exam(connection, columns, values):
    column_names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    sql = f"""
        INSERT INTO exams ({column_names})
        VALUES ({placeholders})
    """

    connection.execute(sql, values)
    connection.commit()


def print_all_exams(connection):
    cursor = connection.execute(
        "SELECT * FROM exams"
    )

    exams = cursor.fetchall()

    for exam in exams:
        print(f"ID: {exam[0]}")
        print(f"Name: {exam[1]}")
        print(f"Category: {exam[2]}")
        print(f"Subject: {exam[3]}")
        print(f"Date: {exam[4]}")
        print(f"Start time: {exam[5]}")
        print(f"End time: {exam[6]}")
        print()


def search_exam(connection, value_name):
    cursor = connection.execute(
        "SELECT * FROM exams WHERE name = ?",
        (value_name,)
    )

    results = cursor.fetchall()

    if results:
        for exam in results:
            print("\n----------------------")
            print("Exam found")
            print("----------------------")
            print(f"ID: {exam[0]}")
            print(f"Name: {exam[1]}")
            print(f"Category: {exam[2]}")
            print(f"Subject: {exam[3]}")
            print(f"Date: {exam[4]}")
            print(f"Start time: {exam[5]}")
            print(f"End time: {exam[6]}")
            print("----------------------")

            return exam[0]

    else:
        print(f"No exam found for {value_name}")

    return None


def search_exams_by_name(connection, value_name):
    cursor = connection.execute(
        "SELECT * FROM exams WHERE name = ?",
        (value_name,)
    )

    return cursor.fetchall()


def delete_exam(connection, exam_id):
    connection.execute(
        "DELETE FROM exams WHERE id = ?",
        (exam_id,)
    )

    connection.commit()


def edit_exam(connection, exam_id, column_name, new_value):
    sql = f"""
        UPDATE exams
        SET {column_name} = ?
        WHERE id = ?
    """

    connection.execute(
        sql,
        (new_value, exam_id)
    )

    connection.commit()


def get_exam_end_time(connection, exam_id):
    cursor = connection.execute(
        "SELECT end_time FROM exams WHERE id = ?",
        (exam_id,)
    )

    result = cursor.fetchone()

    if result:
        return result[0]

    return None


def get_exam_schedule(connection, exam_id):
    cursor = connection.execute(
        """
        SELECT date, start_time, end_time
        FROM exams
        WHERE id = ?
        """,
        (exam_id,)
    )

    return cursor.fetchone()


def get_exam_name_by_id(connection, exam_id):
    cursor = connection.execute(
        "SELECT name FROM exams WHERE id = ?",
        (exam_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return None

    return result[0]


def get_exam_by_id(connection, exam_id):
    cursor = connection.execute(
        "SELECT * FROM exams WHERE id = ?",
        (exam_id,)
    )

    return cursor.fetchone()
