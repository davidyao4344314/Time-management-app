"""Compatibility entry point for backend.app.ai.context.selection."""

import sys
from backend.app.ai.context import selection as _implementation

sys.modules[__name__] = _implementation
