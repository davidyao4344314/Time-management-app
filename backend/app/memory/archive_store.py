"""Compatibility entry point for backend.app.ai.memory.archive_store."""

import sys
from backend.app.ai.memory import archive_store as _implementation

sys.modules[__name__] = _implementation
