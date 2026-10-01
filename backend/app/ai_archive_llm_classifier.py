"""Compatibility import for backend.app.memory.classification."""

import sys
from backend.app.memory import classification as _implementation

sys.modules[__name__] = _implementation
