"""Compatibility entry point for backend.app.integrations.ical_import."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.integrations import ical_import as _implementation

sys.modules[__name__] = _implementation
