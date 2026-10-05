"""Convert a pasted exam timetable into the app's standard exam fields."""
import re
from datetime import date

from backend.app.planner import exam_service, exams

MAX_EXAMS = 100
MONTHS = {name.lower(): index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TABLE_HEADERS = ("course (class number)", "course title", "exam date", "time", "campus", "room", "book")
REQUIRED_HEADERS = ("course (class number)", "exam date", "time")
COURSE_CELL = re.compile(r"[A-Za-z][A-Za-z &/\-]*\s+\d{3}[A-Za-z]?\s*\(\d+\)")


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


def _validate_headers(headers):
    if len(set(headers)) != len(headers) or any(name not in headers for name in REQUIRED_HEADERS):
        raise ExamTableError("The table needs Course (Class Number), Exam Date, and Time columns.")


def _markdown_rows(lines):
    if len(lines) < 3:
        raise ExamTableError("Paste the Markdown table, including its header and separator row.")
    # Follow the header's outer-pipe convention so empty edge cells survive.
    pipe_style = {"leading_pipe": lines[0].startswith("|"),
                  "trailing_pipe": lines[0].endswith("|")}
    headers = [cell.casefold() for cell in _cells(lines[0], **pipe_style)]
    _validate_headers(headers)
    separator = _cells(lines[1], **pipe_style)
    if len(separator) != len(headers) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
        raise ExamTableError("The second row must be the Markdown separator row (---).")
    return headers, [_cells(line, **pipe_style) for line in lines[2:]]


def _copied_rows(lines):
    """Read website/ spreadsheet copies without guessing missing cell boundaries."""
    if "\t" in lines[0]:
        rows = [[cell.strip() for cell in line.split("\t")] for line in lines]
        if TABLE_HEADERS[0] in [cell.casefold() for cell in rows[0]]:
            headers = [cell.casefold() for cell in rows.pop(0)]
            _validate_headers(headers)
        else:
            headers = list(TABLE_HEADERS)
    else:
        cells = [line.strip() for line in lines]
        if cells[0].casefold() == TABLE_HEADERS[0]:
            if tuple(cell.casefold() for cell in cells[:7]) != TABLE_HEADERS:
                raise ExamTableError("Copy all seven timetable columns, including the complete header.")
            cells = cells[7:]
        if not cells or len(cells) % len(TABLE_HEADERS):
            raise ExamTableError("The copied table is incomplete. Copy all seven columns from Course through Book, then preview again.")
        headers = list(TABLE_HEADERS)
        rows = [cells[index:index + 7] for index in range(0, len(cells), 7)]

    if not rows:
        raise ExamTableError("The copied table contains no exams.")
    course_index = headers.index(TABLE_HEADERS[0])
    for index, row in enumerate(rows, 1):
        if len(row) != len(headers) or not COURSE_CELL.fullmatch(row[course_index]):
            raise ExamTableError(f"Exam row {index}: copy the complete timetable row, including its course and class number. Do not paste only part of a row.")
    return headers, rows


def parse_exam_table(text):
    """Preview only: parse Markdown or copied table text without writing SQLite."""
    if not text.strip() or len(text) > 50_000:
        raise ExamTableError("Paste an exam table of no more than 50,000 characters.")
    # Keep tabs at the edges of TSV rows: they can represent empty cells.
    lines = [line.strip(" \r") for line in text.splitlines() if line.strip()]
    if lines and lines[0].startswith("```") and lines[-1] == "```":
        lines = lines[1:-1]
    if not lines:
        raise ExamTableError("Paste an exam timetable before previewing.")
    headers, rows = (_markdown_rows(lines) if "|" in lines[0] and "\t" not in lines[0]
                     else _copied_rows(lines))
    if len(rows) > MAX_EXAMS:
        raise ExamTableError(f"Import at most {MAX_EXAMS} exams at a time.")

    result = []
    for row_number, cells in enumerate(rows, 1):
        if len(cells) != len(headers):
            raise ExamTableError(f"Exam row {row_number}: the number of columns does not match the header.")
        row = dict(zip(headers, cells))
        subject = re.sub(r"\s*\(\d+\)\s*$", "", row[REQUIRED_HEADERS[0]]).strip()
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
