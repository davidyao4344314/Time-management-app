"""Compatibility entry point for backend.app.ai.compat.proposal."""

import sys
from backend.app.ai.compat import proposal as _implementation

sys.modules[__name__] = _implementation
