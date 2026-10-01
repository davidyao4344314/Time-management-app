"""Compatibility entry point for backend.app.ai.agent.contracts."""

import sys
from backend.app.ai.agent import contracts as _implementation

sys.modules[__name__] = _implementation
