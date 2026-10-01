"""Compatibility entry point for backend.app.ai.observations.exams."""

import sys
from backend.app.ai.observations import exams as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
