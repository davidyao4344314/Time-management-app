"""Compatibility import for backend.app.memory.category_review."""

import sys
from backend.app.memory import category_review as _implementation

sys.modules[__name__] = _implementation
