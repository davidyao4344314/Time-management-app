"""Named planner rows that remain tuple-compatible for older callers."""

from collections import namedtuple


ActivityRecord = namedtuple(
    "ActivityRecord",
    "id name category subject activity_type date weekday start_time end_time "
    "active_start_date active_end_date source external_id",
    defaults=(None, None, "Manual", None),
)
ExamRecord = namedtuple(
    "ExamRecord", "id name category subject date start_time end_time source external_id",
    defaults=("Manual", None),
)


def record_cursor(connection, sql, record_type, parameters=()):
    """Map fields using the actual query column names, not table column order."""
    cursor = connection.cursor()

    def make_record(cursor, values):
        columns = (column[0] for column in cursor.description)
        return record_type(**{name: value for name, value in zip(columns, values)
                              if name in record_type._fields})

    cursor.row_factory = make_record
    return cursor.execute(sql, parameters)


def as_activity_record(activity):
    return activity if isinstance(activity, ActivityRecord) else ActivityRecord(*activity)


def as_exam_record(exam):
    return exam if isinstance(exam, ExamRecord) else ExamRecord(*exam)
