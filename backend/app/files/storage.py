"""Owner-scoped normalized files in the existing SQLite database."""

from datetime import datetime, timezone
from uuid import uuid4


def migrate(connection):
    """Additive migration; never replace planner, conversation or memory data."""
    with connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS imported_files(
            file_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL CHECK(file_type IN ('txt','pdf','docx')),
            created_at TEXT NOT NULL,
            text TEXT NOT NULL,
            chunk_count INTEGER NOT NULL CHECK(chunk_count > 0)
        )''')
        connection.execute('''CREATE TABLE IF NOT EXISTS imported_file_chunks(
            chunk_id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES imported_files(file_id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            section TEXT,
            UNIQUE(file_id, position)
        )''')
        connection.execute('CREATE INDEX IF NOT EXISTS imported_files_owner ON imported_files(owner_id, filename)')


def save_file(connection, owner_id, parsed):
    if not isinstance(owner_id, str) or not owner_id:
        raise ValueError("A trusted owner identity is required.")
    file_id = "file_" + uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection:
        connection.execute('INSERT INTO imported_files VALUES(?,?,?,?,?,?,?)',
                           (file_id, owner_id, parsed["filename"], parsed["file_type"],
                            timestamp, parsed["text"], len(parsed["chunks"])))
        connection.executemany('INSERT INTO imported_file_chunks VALUES(?,?,?,?,?,?)', [
            (f"{file_id}_chunk_{index:04d}", file_id, index, chunk["text"], chunk["page"], chunk["section"])
            for index, chunk in enumerate(parsed["chunks"], 1)
        ])
    return get_file(connection, owner_id, file_id, include_content=False)


def _metadata(row):
    return dict(zip(("file_id", "filename", "file_type", "created_at", "chunk_count"), row))


def list_files(connection, owner_id, *, limit=100, offset=0):
    return [_metadata(row) for row in connection.execute('''SELECT file_id,filename,file_type,created_at,chunk_count
        FROM imported_files WHERE owner_id=? ORDER BY created_at DESC,file_id LIMIT ? OFFSET ?''',
        (owner_id, min(max(limit, 1), 100), max(offset, 0)))]


def get_file(connection, owner_id, file_id, *, include_content=True):
    row = connection.execute('''SELECT file_id,filename,file_type,created_at,chunk_count
        FROM imported_files WHERE owner_id=? AND file_id=?''', (owner_id, file_id)).fetchone()
    if row is None:
        return None
    result = _metadata(row)
    if include_content:
        result["text"] = connection.execute('SELECT text FROM imported_files WHERE file_id=?', (file_id,)).fetchone()[0]
        result["chunks"] = [dict(zip(("chunk_id", "position", "text", "page", "section"), chunk))
                            for chunk in connection.execute('''SELECT chunk_id,position,text,page,section
                                FROM imported_file_chunks WHERE file_id=? ORDER BY position''', (file_id,))]
    return result
