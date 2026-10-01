"""Compatibility import for backend.app.dev.observation_smoke."""

import sys
from backend.app.dev import observation_smoke as _implementation

sys.modules[__name__] = _implementation
