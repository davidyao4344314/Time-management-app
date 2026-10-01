"""Compatibility entry point for backend.app.context.selection."""

import sys
from backend.app.context import selection as _implementation

sys.modules[__name__] = _implementation
