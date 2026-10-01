"""Compatibility entry point for backend.app.ai.memory.durable_store."""

import sys
from backend.app.ai.memory import durable_store as _implementation

sys.modules[__name__] = _implementation
