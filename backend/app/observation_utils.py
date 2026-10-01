"""Compatibility entry point for backend.app.ai.observations.formatting."""

import sys
from backend.app.ai.observations import formatting as _implementation

sys.modules[__name__] = _implementation
