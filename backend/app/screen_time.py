"""Compatibility script for the Screen Time manual example."""
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.screen_time import storage

if __name__ == "__main__":
    storage.main()
