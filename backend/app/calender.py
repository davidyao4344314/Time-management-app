"""Compatibility entry point for backend.app.planner.calendar."""

import sys
from backend.app.planner import calendar as _implementation

sys.modules[__name__] = _implementation
