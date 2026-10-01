"""Compatibility import for backend.app.memory.summary."""

import sys
from backend.app.memory import summary as _implementation

sys.modules[__name__] = _implementation
