"""Compatibility entry point for backend.app.context.intent."""

import sys
from backend.app.context import intent as _implementation

sys.modules[__name__] = _implementation
