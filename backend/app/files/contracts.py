"""Small limits and validated managed-file references; no filesystem access."""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 250_000
MAX_PDF_PAGES = 100
CHUNK_CHARS = 2400
MAX_FILE_REFS = 3
MAX_CONTEXT_CHUNKS = 5
MAX_CONTEXT_CHARS = 8000
MAX_QUERY_CHARS = 300
FILE_ID_PATTERN = r"^file_[a-f0-9]{32}$"
FileId = Annotated[str, Field(pattern=FILE_ID_PATTERN)]


class FileImportError(ValueError):
    """Safe, user-facing error; never include parser internals or local paths."""


def validate_filename(filename):
    if (not isinstance(filename, str) or not filename.strip() or len(filename) > 200
            or filename != filename.strip() or any(c in filename for c in ("/", "\\", "\x00"))
            or any(ord(c) < 32 for c in filename) or filename in {".", ".."}):
        raise FileImportError("Use a filename, not a filesystem path (maximum 200 characters).")
    return filename


def validate_query(query):
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ValueError("File search needs 1–300 characters.")
    query = query.strip()
    if (re.search(r"(?:^|\s)(?:~|[a-zA-Z]:)", query)
            or "/" in query or "\\" in query or "://" in query
            or "\x00" in query or any(ord(c) < 32 for c in query)):
        raise ValueError("Search managed files by topic or filename, not paths or URLs.")
    return query


class FileSelection(BaseModel):
    """IDs/names belong to the local index, never arbitrary machine files."""

    model_config = ConfigDict(extra="forbid", strict=True)
    file_ids: list[FileId] = Field(default_factory=list, max_length=MAX_FILE_REFS)
    filename: str | None = Field(default=None, max_length=200)
    query: str | None = Field(default=None, max_length=MAX_QUERY_CHARS)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        return validate_filename(value) if value is not None else None

    @field_validator("query")
    @classmethod
    def safe_query(cls, value):
        return validate_query(value) if value is not None else None

    @model_validator(mode="after")
    def valid_reference(self):
        if not (self.file_ids or self.filename or self.query):
            raise ValueError("Select a managed file ID, filename or search query.")
        if len(self.file_ids) != len(set(self.file_ids)):
            raise ValueError("File references must be unique.")
        if self.file_ids and self.filename:
            raise ValueError("Choose IDs or a filename, not both.")
        return self
