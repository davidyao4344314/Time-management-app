"""Compatibility entry point for backend.app.ai.memory.durable."""

import sys
from backend.app.ai.memory import durable as _implementation

sys.modules[__name__] = _implementation
