"""Compatibility entry point for backend.app.planner.exams."""

import sys
from backend.app.planner import exams as _implementation

sys.modules[__name__] = _implementation
