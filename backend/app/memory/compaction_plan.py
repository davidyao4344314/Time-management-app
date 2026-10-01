"""Compatibility entry point for backend.app.ai.memory.compaction_plan."""

import sys
from backend.app.ai.memory import compaction_plan as _implementation

sys.modules[__name__] = _implementation
