"""Compatibility entry point for backend.app.ai.memory.settings."""

import sys
from backend.app.ai.memory import settings as _implementation

sys.modules[__name__] = _implementation
