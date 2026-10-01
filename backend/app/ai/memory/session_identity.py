"""Authenticate conversation cookies independently of the recent-memory cache."""

import hashlib
import hmac
import os
import re
import secrets

from backend.app.ai.memory import archive_store
from backend.app.infrastructure.atomic_files import exclusive_file_lock


def _signing_key():
    # Persistent, private, local-only secret. Follow archive path overrides in tests.
    path = archive_store.ARCHIVE_FILE.with_name(".ai_session_key")
    with exclusive_file_lock(path):
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            return key
        with os.fdopen(fd, "rb") as stream:
            key = stream.read()
        if len(key) != 32:
            raise OSError("Conversation signing key is invalid.")
        return key


def sign_session(session_id):
    return hmac.new(_signing_key(), session_id.encode("ascii"), hashlib.sha256).hexdigest()


def valid_session(session_id, signature):
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
        return False
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    return hmac.compare_digest(sign_session(session_id), signature)
