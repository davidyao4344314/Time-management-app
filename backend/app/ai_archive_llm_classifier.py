"""Compatibility import for backend.app.ai.memory.classification."""

import sys
from backend.app.ai.memory import classification as _implementation

sys.modules[__name__] = _implementation
