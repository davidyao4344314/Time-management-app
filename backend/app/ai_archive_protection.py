"""Compatibility import for backend.app.ai.memory.protection."""

import sys
from backend.app.ai.memory import protection as _implementation

sys.modules[__name__] = _implementation
