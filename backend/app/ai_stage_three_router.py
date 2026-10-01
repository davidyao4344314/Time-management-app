"""Compatibility entry point for backend.app.context.fallback."""

import sys
from backend.app.context import fallback as _implementation

sys.modules[__name__] = _implementation
