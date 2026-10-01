"""Compatibility import for backend.app.memory.compaction."""

import sys
from backend.app.memory import compaction as _implementation

sys.modules[__name__] = _implementation
