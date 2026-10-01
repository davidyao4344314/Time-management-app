"""Compatibility entry point for backend.app.ai.compat.durable_memory."""

import sys
from backend.app.ai.compat import durable_memory as _implementation

sys.modules[__name__] = _implementation
