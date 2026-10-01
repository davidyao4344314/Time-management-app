"""Compatibility entry point for backend.app.context.keywords."""

import sys
from backend.app.context import keywords as _implementation

sys.modules[__name__] = _implementation
