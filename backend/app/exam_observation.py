"""Compatibility entry point for backend.app.observations.exams."""

import sys
from backend.app.observations import exams as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
