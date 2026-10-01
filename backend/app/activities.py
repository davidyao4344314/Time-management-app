"""Compatibility entry point for backend.app.planner.activities."""

import sys
from backend.app.planner import activities as _implementation

sys.modules[__name__] = _implementation
