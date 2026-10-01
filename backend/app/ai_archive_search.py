"""Compatibility import for backend.app.ai.memory.search."""

import sys
from backend.app.ai.memory import search as _implementation

sys.modules[__name__] = _implementation
