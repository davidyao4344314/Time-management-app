"""Compatibility import for backend.app.ai.memory.compaction."""

import sys
from backend.app.ai.memory import compaction as _implementation

sys.modules[__name__] = _implementation
