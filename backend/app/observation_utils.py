"""Compatibility entry point for backend.app.observations.formatting."""

import sys
from backend.app.observations import formatting as _implementation

sys.modules[__name__] = _implementation
