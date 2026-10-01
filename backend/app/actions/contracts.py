"""Compatibility entry point for backend.app.ai.actions.contracts."""

import sys
from backend.app.ai.actions import contracts as _implementation

sys.modules[__name__] = _implementation
