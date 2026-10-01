"""Compatibility entry point for backend.app.ai.memory.contracts."""

import sys
from backend.app.ai.memory import contracts as _implementation

sys.modules[__name__] = _implementation
