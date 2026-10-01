"""Compatibility entry point for backend.app.ai.context.keywords."""

import sys
from backend.app.ai.context import keywords as _implementation

sys.modules[__name__] = _implementation
