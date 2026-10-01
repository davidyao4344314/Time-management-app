"""Compatibility entry point for backend.app.ai.memory.selection."""

import sys
from backend.app.ai.memory import selection as _implementation

sys.modules[__name__] = _implementation
