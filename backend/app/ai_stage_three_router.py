"""Compatibility entry point for backend.app.ai.context.fallback."""

import sys
from backend.app.ai.context import fallback as _implementation

sys.modules[__name__] = _implementation
