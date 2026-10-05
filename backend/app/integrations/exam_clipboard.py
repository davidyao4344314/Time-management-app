"""Convert a pasted exam timetable into the app's standard exam fields."""
import re
from datetime import date

from backend.app.planner import exam_service, exams

MAX_EXAMS = 100
MONTHS = {name.lower(): index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ExamTableError(ValueError):
    """A pasted table or reviewed exam contains an invalid value."""


def _cells(line, *, leading_pipe, trailing_pipe):
    # Escaped pipes in course titles are content, not column separators.
    line = line.strip()
    if leading_pipe and line.startswith("|"):
        line = line[1:]
    if trailing_pipe and line.endswith("|"):
        line = line[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in
            re.split(r"(?<!\\)\|", line)]


def _exam_date(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    match = re.fullmatch(r"(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})",
                         value, re.IGNORECASE)
    if not match or match[3].lower() not in MONTHS:
        raise ValueError("Use a date such as Mon 02 Nov 2026 or 2026-11-02.")
    parsed = date(int(match[4]), MONTHS[match[3].lower()], int(match[2]))
    if match[1] and WEEKDAYS[parsed.weekday()] != match[1].lower():
        raise ValueError("The weekday does not match the exam date.")
    return parsed.isoformat()


def _time_range(value):
    if value.lower() in {"", "tba", "no time set", "-"}:
        return None, None
    match = re.fullmatch(r"(\d{2}:\d{2})\s*[-–—]\s*(\d{2}:\d{2})", value)
    if not match:
        raise ValueError("Use a time range such as 09:00 - 11:15, or leave it blank.")
    return match[1], match[2]


def parse_exam_table(text):
    """Preview only: parse a Markdown table without opening or writing SQLite."""
    if not text.strip() or len(text) > 50_000:
        raise ExamTableError("Paste an exam table of no more than 50,000 characters.")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0].startswith("```") and lines[-1] == "```":
        lines = lines[1:-1]
    if len(lines) < 3 or "|" not in lines[0]:
        raise ExamTableError("Paste the Markdown table, including its header and separator row.")
    # Follow the header's outer-pipe convention so empty edge cells survive.
    pipe_style = {"leading_pipe": lines[0].startswith("|"),
                  "trailing_pipe": lines[0].endswith("|")}
    headers = [cell.casefold() for cell in _cells(lines[0], **pipe_style)]
    required = ("course (class number)", "exam date", "time")
    if len(set(headers)) != len(headers) or any(name not in headers for name in required):
        raise ExamTableError("The table needs Course (Class Number), Exam Date, and Time columns.")
    separator = _cells(lines[1], **pipe_style)
    if len(separator) != len(headers) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
        raise ExamTableError("The second row must be the Markdown separator row (---).")
    if len(lines) - 2 > MAX_EXAMS:
        raise ExamTableError(f"Import at most {MAX_EXAMS} exams at a time.")

    result = []
    for row_number, line in enumerate(lines[2:], 1):
        cells = _cells(line, **pipe_style)
        if len(cells) != len(headers):
            raise ExamTableError(f"Exam row {row_number}: the number of columns does not match the header.")
        row = dict(zip(headers, cells))
        subject = re.sub(r"\s*\(\d+\)\s*$", "", row[required[0]]).strip()
        if not subject:
            raise ExamTableError(f"Exam row {row_number}: the course is missing.")
        try:
            start, end = _time_range(row["time"])
            columns, values = exam_service.prepare_new_exam({
                "name": f"{subject} Exam", "category": "University", "subject": subject,
                "date": _exam_date(row["exam date"]), "start_time": start, "end_time": end,
            })
        except exam_service.ExamValidationError as error:
            raise ExamTableError(f"Exam row {row_number}: {error.detail}") from None
        except ValueError as error:
            raise ExamTableError(f"Exam row {row_number}: {error}") from None
        result.append(dict(zip(columns, values)))
    return result


def prepare_exam_import(rows):
    """Validate the complete reviewed batch before any records are inserted."""
    if not rows or len(rows) > MAX_EXAMS:
        raise ExamTableError(f"Import between 1 and {MAX_EXAMS} exams.")
    prepared = []
    for index, fields in enumerate(rows, 1):
        try:
            columns, values = exam_service.prepare_new_exam(fields)
        except exam_service.ExamValidationError as error:
            raise ExamTableError(f"Exam {index}: {error.detail}") from None
        prepared.append(([*columns, "source", "external_id"], [*values, "Manual", None]))
    return prepared


def save_exam_import(connection, prepared):
    """Reuse add_exam(), with one transaction for the batch and duplicate checks."""
    imported = duplicates = 0
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        for columns, values in prepared:
            if exams.exam_exists(connection, columns, values):
                duplicates += 1
                continue
            exams.add_exam(connection, columns, values, commit=False)
            imported += 1
    return {"imported": imported, "duplicates_skipped": duplicates}
