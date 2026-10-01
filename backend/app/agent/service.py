"""Compatibility entry point for backend.app.ai.agent.service."""

import sys
from backend.app.ai.agent import service as _implementation

sys.modules[__name__] = _implementation
