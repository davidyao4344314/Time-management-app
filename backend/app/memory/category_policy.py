"""Compatibility entry point for backend.app.ai.memory.category_policy."""

import sys
from backend.app.ai.memory import category_policy as _implementation

sys.modules[__name__] = _implementation
