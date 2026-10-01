"""Compatibility import for backend.app.memory.protection."""

import sys
from backend.app.memory import protection as _implementation

sys.modules[__name__] = _implementation
