"""Compatibility entry point for backend.app.ai.observations.collect."""

import sys
from backend.app.ai.observations import collect as _implementation

sys.modules[__name__] = _implementation
