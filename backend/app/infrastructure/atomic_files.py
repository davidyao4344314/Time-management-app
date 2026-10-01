"""Private file reads, verified temporary writes, syncing, and sidecar locks.

Callers still own backup/replacement/recovery order and choose storage paths.
Importing this module does not read or write any memory files.
"""

import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager

from backend.app.infrastructure.errors import MemoryUtilityError


def read_regular_bytes(path):
    """Read an existing regular file without following a final-path symlink."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MemoryUtilityError("The archive is not a regular file.")
        with os.fdopen(descriptor, "rb", closefd=False) as archive:
            return archive.read()
    finally:
        os.close(descriptor)


def write_verified_temp(directory, data, *, read_bytes=None):
    """Write private, fsynced temporary bytes and verify them by reading back.

    Preserve the existing temporary-file prefix and allow a caller-supplied
    reader so existing storage failure checks can use the same verification.
    """
    reader = read_regular_bytes if read_bytes is None else read_bytes
    descriptor, path = tempfile.mkstemp(prefix=".archive-stage5-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(data)
            output.flush()
            os.fsync(descriptor)
        if reader(path) != data:
            raise MemoryUtilityError("A temporary archive write could not be verified.")
        return path
    except Exception:
        os.unlink(path)
        raise
    finally:
        os.close(descriptor)


def fsync_directory(directory):
    """Flush directory metadata after a caller replaces or restores a file."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def exclusive_file_lock(path, *, require_regular_file=False,
                        regular_file_error="The memory lock must be a regular file."):
    """Lock a stable private sidecar inode across appends and replacements."""
    lock_path = path.with_name(path.name + ".lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if require_regular_file and not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(regular_file_error)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
