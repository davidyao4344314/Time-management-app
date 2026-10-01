"""Compatibility entry point for backend.app.ai.observations.screen_time."""

import sys
from backend.app.ai.observations import screen_time as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
