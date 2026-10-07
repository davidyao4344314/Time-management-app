"""Validated activity use cases, independent of HTTP and the AI agent.

These functions do not execute agent proposals. They reuse existing CRUD and
leave connection lifetime with their caller.
"""

from datetime import date, datetime

from backend.app.planner.activities import add_activity, delete_activity, edit_activity, get_activity_by_id

EDITABLE_ACTIVITY_COLUMNS = ("name", "category", "subject", "activity_type", "date", "weekday", "start_time", "end_time")


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


def get_activity_target(connection, activity_id, expected_name):
    """Read the exact target for preview/preflight, without changing SQLite."""
    activity = get_activity_by_id(connection, activity_id)
    if activity is None:
        raise ActivityValidationError(status_code=404, detail="Activity no longer exists. Request a new proposal.")
    if activity[1] != expected_name:
        raise ActivityValidationError(status_code=409, detail="Activity name no longer matches. Request a new proposal.")
    columns = ("id", "name", "category", "subject", "activity_type", "date", "weekday",
               "start_time", "end_time", "active_start_date", "active_end_date", "source")
    return dict(zip(columns, activity))


def prepare_activity_deletion(connection, activity_id, expected_name):
    return get_activity_target(connection, activity_id, expected_name)


def prepare_activity_update(connection, activity_id, expected_name, changes):
    """Validate a final activity and compute its requested updates without writing."""
    target = get_activity_target(connection, activity_id, expected_name)
    if not isinstance(changes, list) or not 1 <= len(changes) <= len(EDITABLE_ACTIVITY_COLUMNS):
        raise ActivityValidationError(status_code=400, detail="Choose one or more editable fields.")
    requested = {}
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {"column_name", "new_value"}
                or change["column_name"] not in EDITABLE_ACTIVITY_COLUMNS
                or change["column_name"] in requested
                or (change["new_value"] is not None and not isinstance(change["new_value"], str))):
            raise ActivityValidationError(status_code=400, detail="The requested activity fields are invalid.")
        requested[change["column_name"]] = change["new_value"]
    fields = {column: target[column] for column in EDITABLE_ACTIVITY_COLUMNS}
    fields.update(requested)
    activity_type = fields.get("activity_type")
    if activity_type not in {"one_time", "daily", "weekly"}:
        raise ActivityValidationError(status_code=400, detail="Invalid activity type.")
    # Never silently accept a requested non-null value for an inapplicable field.
    if activity_type != "one_time" and requested.get("date") is not None:
        raise ActivityValidationError(status_code=400, detail="Date is only used for one-time activities.")
    if activity_type != "weekly" and requested.get("weekday") is not None:
        raise ActivityValidationError(status_code=400, detail="Weekday is only used for weekly activities.")
    touched = set(requested)
    if "activity_type" in requested:
        touched.update(("date", "weekday"))
        if activity_type != "one_time":
            fields["date"] = None
        if activity_type != "weekly":
            fields["weekday"] = None
    if not fields.get("name") or not fields.get("category"):
        raise ActivityValidationError(status_code=400, detail="Name and category are required.")
    columns, values = prepare_new_activity(fields)
    normalized = dict(zip(columns, values))
    updates = {column: normalized[column] for column in EDITABLE_ACTIVITY_COLUMNS
               if column in touched and normalized[column] != target[column]}
    if not updates:
        raise ActivityValidationError(status_code=400, detail="The proposed edit does not change this activity.")
    return target, updates


def update_activity_fields(connection, activity_id, expected_name, changes):
    """Update in place through existing CRUD; final-value validation and writes are atomic."""
    if connection.in_transaction:
        raise ActivityValidationError(status_code=409, detail="Editing needs its own transaction.")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        _, updates = prepare_activity_update(connection, activity_id, expected_name, changes)
        for column, value in updates.items():
            edit_activity(connection, activity_id, column, value, commit=False)
    return {"activity_id": activity_id, "updated": True, "fields": list(updates)}


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

    column_name = fields["column_name"].strip()

    if column_name not in EDITABLE_ACTIVITY_COLUMNS:
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
