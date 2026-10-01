"""Compatibility entry point for backend.app.ai.context.intent."""

import sys
from backend.app.ai.context import intent as _implementation

sys.modules[__name__] = _implementation
