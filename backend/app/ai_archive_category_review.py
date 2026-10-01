"""Compatibility import for backend.app.ai.memory.category_review."""

import sys
from backend.app.ai.memory import category_review as _implementation

sys.modules[__name__] = _implementation
