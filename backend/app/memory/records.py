"""Compatibility entry point for backend.app.ai.memory.records."""

import sys
from backend.app.ai.memory import records as _implementation

sys.modules[__name__] = _implementation
