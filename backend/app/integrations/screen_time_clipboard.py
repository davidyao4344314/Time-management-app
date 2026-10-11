"""Parse pasted daily Screen Time text without I/O, storage or AI calls.

Supported rows are ``name: duration``, ``name duration`` or a name followed
by a duration on the next non-blank line. Only a labelled Total supplies the
daily total: missing totals stay None, never the sum of the listed apps.
App rows need not add up to the total. Repeated labels keep the first value
with a warning rather than silently combining or replacing usage.

Pass selected_date as YYYY-MM-DD; otherwise the app's Auckland date is used.
Yesterday requires an explicit date. Weekly/average summaries are rejected
because they cannot safely be converted into one daily record.

Result: {success: bool, data: dict | None, warnings: list, errors: list}.
Warnings have a code, message and optional one-based input line number.
Partial valid data can succeed with warnings; callers should review them.
"""

import re
from datetime import date

from backend.app.infrastructure.clock import local_now

MAX_PASTE_CHARACTERS = 50_000
_DURATION_PATTERN = (
    r"(?:(?P<hours>[0-9]+)\s*(?:hours?|hrs?|h)\s*)?"
    r"(?:(?P<minutes>[0-9]+)\s*(?:minutes?|mins?|m))?"
)
_DURATION = re.compile(_DURATION_PATTERN, re.IGNORECASE)
_INLINE_ROW = re.compile(
    rf"(?P<name>.+?)(?:\s*:\s*|\s+)(?P<duration>{_DURATION_PATTERN})",
    re.IGNORECASE,
)
_HEADINGS = {"screen time", "today", "most used", "apps", "app usage"}
_TOTAL_LABELS = {"total", "total time", "total screen time"}
_AGGREGATE_LABELS = {"this week", "last week", "weekly average", "daily average"}


def parse_duration_to_minutes(text):
    """Return integer minutes; reject negatives, fractions and unknown units."""
    message = "Use a duration such as 4h 12m, 52 min or 1 hour 20 minutes."
    if not isinstance(text, str):
        raise ValueError(message)
    match = _DURATION.fullmatch(text.strip())
    if match is None or all(value is None for value in match.groupdict().values()):
        raise ValueError(message)
    try:
        return int(match["hours"] or 0) * 60 + int(match["minutes"] or 0)
    except ValueError:
        raise ValueError(message) from None


def parse_screen_time_text(text, selected_date=None):
    """Normalize text only. Never access the clipboard, network or database."""
    warnings = []

    def failure(message):
        return {"success": False, "data": None, "warnings": warnings, "errors": [message]}

    def warn(code, message, line=None):
        warnings.append({"code": code, "line": line, "message": message})

    if not isinstance(text, str) or not text.strip():
        return failure("Paste daily Screen Time text before parsing.")
    if len(text) > MAX_PASTE_CHARACTERS:
        return failure(f"Paste no more than {MAX_PASTE_CHARACTERS:,} characters.")
    if selected_date is None:
        chosen_date = local_now().date().isoformat()
    else:
        try:
            chosen_date = date.fromisoformat(selected_date).isoformat()
            if chosen_date != selected_date:
                raise ValueError
        except (TypeError, ValueError):
            return failure("Date must be a real calendar date in YYYY-MM-DD format.")

    total_minutes = None
    apps = []
    app_names = set()
    pending = None

    def abandon_pending():
        nonlocal pending
        if pending is not None:
            warn("missing_duration", "This label has no usable duration and was ignored.", pending[1])
            pending = None

    def record(label, duration, line_number):
        nonlocal total_minutes
        try:
            minutes = parse_duration_to_minutes(duration)
        except ValueError as error:
            warn("invalid_duration", str(error), line_number)
            return
        if label.casefold() in _TOTAL_LABELS:
            if total_minutes is not None:
                warn("duplicate_total", "Repeated total ignored; the first total was kept.", line_number)
            else:
                total_minutes = minutes
        elif label.casefold() in app_names:
            warn("duplicate_app", "Repeated app ignored; the first value was kept.", line_number)
        else:
            apps.append({"name": label, "minutes": minutes})
            app_names.add(label.casefold())

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        label = line.rstrip(":").strip()
        lowered = label.casefold()
        if lowered in _AGGREGATE_LABELS:
            return failure("Paste a single day's usage, not a weekly or average summary.")
        if lowered == "yesterday":
            if selected_date is None:
                return failure("Select an explicit date for yesterday's Screen Time.")
            abandon_pending()
            continue
        if lowered in _HEADINGS:
            abandon_pending()
            continue
        if lowered in _TOTAL_LABELS:
            abandon_pending()
            pending = (label, line_number)
            continue

        try:
            parse_duration_to_minutes(line)
        except ValueError:
            pass
        else:
            if pending is None:
                warn("unlabelled_duration", "A duration without an app or Total label was ignored.", line_number)
            else:
                record(pending[0], line, line_number)
                pending = None
            continue

        inline = _INLINE_ROW.fullmatch(line)
        if inline is not None:
            abandon_pending()
            record(inline["name"].strip(), inline["duration"], line_number)
        elif ":" in line:
            abandon_pending()
            name, duration = line.split(":", 1)
            if name.strip():
                record(name.strip(), duration.strip(), line_number)
            else:
                warn("missing_label", "A row without an app or Total label was ignored.", line_number)
        elif re.match(r"^[+-]?[0-9]+(?:\s|[.:]|[hm](?=\s|[0-9]|$))", line, re.IGNORECASE):
            # Recognize an invalid duration-shaped line without treating it as
            # a new app name. Names like 1Password remain ordinary labels.
            pending = None
            warn("invalid_duration", "Invalid duration ignored; use hours/minutes with units.", line_number)
        else:
            abandon_pending()
            pending = (line, line_number)

    abandon_pending()
    if total_minutes is None and not apps:
        return failure("No usable Total or app durations found. Paste labelled daily usage.")
    if total_minutes is None:
        warn("missing_total", "Total was not provided; total_minutes is null, not the sum of apps.")
    return {
        "success": True,
        "data": {"date": chosen_date, "total_minutes": total_minutes,
                 "apps": apps, "source": "clipboard"},
        "warnings": warnings,
        "errors": [],
    }


def main():
    """Print a synthetic parsing example only; nothing is saved."""
    import json

    sample = "Screen Time\nToday\nTotal: 4h 12m\nYouTube\n1h 24m\nInstagram\n52m\nSafari\n35m"
    print(json.dumps(parse_screen_time_text(sample, "2026-10-11"), indent=2))


if __name__ == "__main__":
    main()
