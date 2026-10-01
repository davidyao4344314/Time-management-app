"""Compatibility entry point for backend.app.ai.memory.paths."""

import sys
from backend.app.ai.memory import paths as _implementation

sys.modules[__name__] = _implementation
