"""Compatibility import for backend.app.ai.memory.summary."""

import sys
from backend.app.ai.memory import summary as _implementation

sys.modules[__name__] = _implementation
