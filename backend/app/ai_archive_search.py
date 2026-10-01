"""Compatibility import for backend.app.memory.search."""

import sys
from backend.app.memory import search as _implementation

sys.modules[__name__] = _implementation
