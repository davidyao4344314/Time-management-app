"""Compatibility entry point for backend.app.ai.memory.recent."""

import sys
from backend.app.ai.memory import recent as _implementation

sys.modules[__name__] = _implementation
