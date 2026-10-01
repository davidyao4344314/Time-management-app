"""Compatibility entry point for backend.app.planner.activity_service."""

import sys
from backend.app.planner import activity_service as _implementation

sys.modules[__name__] = _implementation
