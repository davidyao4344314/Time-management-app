"""Validated activity use cases, independent of HTTP and the AI agent.

These functions do not execute agent proposals. They reuse existing CRUD and
leave connection lifetime with their caller.
"""

from datetime import date, datetime

from backend.app.planner.activities import add_activity, delete_activity, edit_activity, get_activity_by_id


class ActivityValidationError(ValueError):
    """An expected validation failure; the HTTP adapter maps it to a response."""

    def __init__(self, *, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def normalize_optional_time(value):
    if value is None or not value.strip():
        return None

    return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")


def validate_optional_time_range(start_time, end_time):
    if start_time is None or end_time is None:
        return

    parsed_start = datetime.strptime(start_time, "%H:%M")
    parsed_end = datetime.strptime(end_time, "%H:%M")

    if parsed_start >= parsed_end:
        raise ActivityValidationError(
            status_code=400,
            detail="End time must be later than start time.",
        )


def prepare_new_activity(fields):
    name = fields.get("name").strip()
    category = fields.get("category").strip()
    subject = fields.get("subject").strip() if fields.get("subject") else None
    activity_type = fields.get("activity_type").strip().lower()

    if not name or not category:
        raise ActivityValidationError(status_code=400, detail="Name and category are required.")

    if activity_type not in {"one_time", "daily", "weekly"}:
        raise ActivityValidationError(status_code=400, detail="Invalid activity type.")

    try:
        start_time = normalize_optional_time(fields.get("start_time"))
        end_time = normalize_optional_time(fields.get("end_time"))
    except (AttributeError, ValueError):
        raise ActivityValidationError(
            status_code=400,
            detail="Times must use HH:MM format.",
        ) from None

    validate_optional_time_range(start_time, end_time)

    activity_date = None
    weekday = None

    if activity_type == "one_time":
        if not fields.get("date"):
            raise ActivityValidationError(
                status_code=400,
                detail="A date is required for a one-time activity.",
            )

        try:
            activity_date = str(date.fromisoformat(fields.get("date").strip()))
        except ValueError:
            raise ActivityValidationError(
                status_code=400,
                detail="Date must use YYYY-MM-DD format.",
            ) from None

    elif activity_type == "weekly":
        valid_weekdays = {
            "monday": "Monday",
            "tuesday": "Tuesday",
            "wednesday": "Wednesday",
            "thursday": "Thursday",
            "friday": "Friday",
            "saturday": "Saturday",
            "sunday": "Sunday",
        }
        requested_weekday = (
            fields.get("weekday").strip().lower()
            if fields.get("weekday")
            else ""
        )
        weekday = valid_weekdays.get(requested_weekday)

        if weekday is None:
            raise ActivityValidationError(
                status_code=400,
                detail="A valid weekday is required for a weekly activity.",
            )

    columns = [
        "name",
        "category",
        "subject",
        "activity_type",
        "date",
        "weekday",
        "start_time",
        "end_time",
    ]
    values = [
        name,
        category,
        subject,
        activity_type,
        activity_date,
        weekday,
        start_time,
        end_time,
    ]

    return columns, values


def create_activity_record(connection, prepared):
    """Insert through the existing CRUD function and return its new row."""
    columns, values = prepared
    activity_id = add_activity(connection, columns, values)
    return get_activity_by_id(connection, activity_id)


def prepare_activity_deletion(connection, activity_id, expected_name):
    """Read the exact target for preview/preflight, without changing SQLite."""
    activity = get_activity_by_id(connection, activity_id)
    if activity is None:
        raise ActivityValidationError(status_code=404, detail="Activity no longer exists. Request a new proposal.")
    if activity[1] != expected_name:
        raise ActivityValidationError(status_code=409, detail="Activity name no longer matches. Request a new proposal.")
    columns = ("id", "name", "category", "subject", "activity_type", "date", "weekday",
               "start_time", "end_time", "active_start_date", "active_end_date", "source")
    return dict(zip(columns, activity))


def delete_activity_record(connection, activity_id, expected_name):
    """Re-check and delete one record under the same SQLite write transaction."""
    if connection.in_transaction:
        raise ActivityValidationError(status_code=409, detail="Deletion needs its own transaction.")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        prepare_activity_deletion(connection, activity_id, expected_name)
        removed = delete_activity(connection, activity_id, commit=False)
        if removed != 1:
            raise ActivityValidationError(status_code=409, detail="The selected activity could not be deleted.")
    return {"activity_id": activity_id, "deleted": True}


def validate_activity_edit(activity_id, fields):
    if fields["activity_id"] != activity_id:
        raise ActivityValidationError(
            status_code=400,
            detail="The activity ID in the URL and request body must match.",
        )

    editable_columns = {
        "name",
        "category",
        "subject",
        "activity_type",
        "date",
        "weekday",
        "start_time",
        "end_time",
    }
    column_name = fields["column_name"].strip()

    if column_name not in editable_columns:
        raise ActivityValidationError(status_code=400, detail="That field cannot be edited.")

    return column_name


def update_activity_record(connection, activity_id, fields):
    """Apply a logical edit atomically, preserving IDs and imported metadata."""
    column_name = validate_activity_edit(activity_id, fields)
    activity = get_activity_by_id(connection, activity_id)

    if activity is None:
        raise ActivityValidationError(status_code=404, detail="Activity ID not found.")

    current_activity_type = activity[4]
    new_value = fields.get("new_value")

    if column_name in {"name", "category"}:
        new_value = new_value.strip() if new_value else ""

        if not new_value:
            field_name = column_name.replace("_", " ").title()
            raise ActivityValidationError(
                status_code=400,
                detail=f"{field_name} is required.",
            )

    elif column_name == "subject":
        new_value = new_value.strip() if new_value else None

    elif column_name == "activity_type":
        new_value = new_value.strip().lower() if new_value else ""

        if new_value not in {"one_time", "daily", "weekly"}:
            raise ActivityValidationError(status_code=400, detail="Invalid activity type.")

        if new_value == "one_time":
            try:
                selected_date = fields.get("date") if fields.get("date") is not None else activity[5]
                selected_date = date.fromisoformat(selected_date.strip()).isoformat()
            except (AttributeError, ValueError):
                raise ActivityValidationError(status_code=400, detail="Choose a date for the one-time activity.") from None
        elif new_value == "weekly":
            selected_weekday = fields.get("weekday") if fields.get("weekday") is not None else activity[6]
            weekdays = {day.lower(): day for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")}
            selected_weekday = weekdays.get(selected_weekday.strip().lower()) if selected_weekday else None
            if selected_weekday is None:
                raise ActivityValidationError(status_code=400, detail="Choose a weekday for the weekly activity.")

    elif column_name == "date":
        if current_activity_type != "one_time":
            raise ActivityValidationError(
                status_code=400,
                detail="Date can only be edited for a one-time activity.",
            )

        try:
            new_value = str(date.fromisoformat(new_value.strip()))
        except (AttributeError, ValueError):
            raise ActivityValidationError(
                status_code=400,
                detail="Date must use YYYY-MM-DD format.",
            ) from None

    elif column_name == "weekday":
        if current_activity_type != "weekly":
            raise ActivityValidationError(
                status_code=400,
                detail="Weekday can only be edited for a weekly activity.",
            )

        valid_weekdays = {
            "monday": "Monday",
            "tuesday": "Tuesday",
            "wednesday": "Wednesday",
            "thursday": "Thursday",
            "friday": "Friday",
            "saturday": "Saturday",
            "sunday": "Sunday",
        }
        requested_weekday = new_value.strip().lower() if new_value else ""
        new_value = valid_weekdays.get(requested_weekday)

        if new_value is None:
            raise ActivityValidationError(status_code=400, detail="Invalid weekday.")

    elif column_name in {"start_time", "end_time"}:
        try:
            new_value = normalize_optional_time(new_value)
        except (AttributeError, ValueError):
            raise ActivityValidationError(
                status_code=400,
                detail="Time must use HH:MM format.",
            ) from None

        start_time_value = new_value if column_name == "start_time" else activity[7]
        end_time_value = new_value if column_name == "end_time" else activity[8]

        try:
            start_time_value = normalize_optional_time(start_time_value)
            end_time_value = normalize_optional_time(end_time_value)
        except (AttributeError, ValueError):
            raise ActivityValidationError(
                status_code=400,
                detail="The stored activity time is invalid.",
            ) from None

        validate_optional_time_range(start_time_value, end_time_value)

    connection.execute("SAVEPOINT activity_edit")
    try:
        edit_activity(connection, activity_id, column_name, new_value, commit=False)

        if column_name == "activity_type":
            if new_value == "one_time":
                edit_activity(connection, activity_id, "date", selected_date, commit=False)
            elif new_value == "weekly":
                edit_activity(connection, activity_id, "weekday", selected_weekday, commit=False)

        resulting_activity_type = (
            new_value if column_name == "activity_type" else current_activity_type
        )

        if resulting_activity_type == "one_time":
            edit_activity(connection, activity_id, "weekday", None, commit=False)
        elif resulting_activity_type == "daily":
            edit_activity(connection, activity_id, "date", None, commit=False)
            edit_activity(connection, activity_id, "weekday", None, commit=False)
        elif resulting_activity_type == "weekly":
            edit_activity(connection, activity_id, "date", None, commit=False)

        updated_activity = get_activity_by_id(connection, activity_id)
        connection.execute("RELEASE SAVEPOINT activity_edit")
        return updated_activity

    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT activity_edit")
        connection.execute("RELEASE SAVEPOINT activity_edit")
        raise
