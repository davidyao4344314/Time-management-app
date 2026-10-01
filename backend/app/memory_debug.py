"""Compatibility CLI for backend.app.dev.memory_debug."""

import sys
from backend.app.dev import memory_debug as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
