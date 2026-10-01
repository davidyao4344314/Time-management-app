"""Compatibility entry point for backend.app.integrations.uoa_timetable_import."""

import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.integrations import uoa_timetable_import as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
