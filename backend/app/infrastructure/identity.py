"""Signed local profile identity; independent of chat or memory contents."""
import hashlib
import hmac
import os
import re
import secrets

from backend.app.infrastructure.paths import BACKEND_DIRECTORY
from backend.app.infrastructure.atomic_files import exclusive_file_lock

IDENTITY_KEY_FILE = BACKEND_DIRECTORY / '.ai_session_key'


def sign_owner(owner_id):
    with exclusive_file_lock(IDENTITY_KEY_FILE):
        try:
            descriptor = os.open(IDENTITY_KEY_FILE, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            descriptor = os.open(IDENTITY_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        else:
            with os.fdopen(descriptor, 'rb') as stream:
                key = stream.read()
        if len(key) != 32:
            raise OSError('Local identity configuration is invalid.')
    return hmac.new(key, owner_id.encode('ascii'), hashlib.sha256).hexdigest()


def valid_owner(owner_id, signature):
    if not isinstance(owner_id, str) or not re.fullmatch(r'[0-9a-f]{32}', owner_id):
        return False
    if not isinstance(signature, str) or not re.fullmatch(r'[0-9a-f]{64}', signature):
        return False
    return hmac.compare_digest(sign_owner(owner_id), signature)
