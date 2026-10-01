"""Compatibility entry point for backend.app.ai.config."""

import sys
from backend.app.ai import config as _implementation

sys.modules[__name__] = _implementation
