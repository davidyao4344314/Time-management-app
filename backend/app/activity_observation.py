"""Compatibility entry point for backend.app.observations.activities."""

import sys
from backend.app.observations import activities as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
