"""Compatibility entry point for backend.app.ai.compat.memory."""

import sys
from backend.app.ai.compat import memory as _implementation

sys.modules[__name__] = _implementation
