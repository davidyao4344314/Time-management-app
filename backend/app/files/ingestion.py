"""Convert uploaded bytes and save normalized content using the file store."""

from backend.app.files.parser import parse_file
from backend.app.files.storage import save_file


def ingest_file(connection, owner_id, filename, data):
    return save_file(connection, owner_id, parse_file(filename, data))
