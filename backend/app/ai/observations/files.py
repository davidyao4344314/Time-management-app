"""Read-only adapter for a trusted owner-scoped file reader."""

import sqlite3
from backend.app.files.contracts import FileSelection


def build_file_observation(selection, *, reader=None):
    selected = FileSelection.model_validate(selection).model_dump()
    if reader is None:
        return {"status": "unavailable", "count": 0, "files": [], "chunks": []}
    try:
        return reader(selected)
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        return {"status": "unavailable", "count": 0, "files": [], "chunks": []}
