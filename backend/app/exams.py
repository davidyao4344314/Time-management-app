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