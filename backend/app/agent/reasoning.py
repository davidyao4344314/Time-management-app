"""Compatibility entry point for backend.app.ai.agent.reasoning."""

import sys
from backend.app.ai.agent import reasoning as _implementation

sys.modules[__name__] = _implementation
