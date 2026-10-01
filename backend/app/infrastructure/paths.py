"""Repository locations, independent of the folders of consuming modules."""

from pathlib import Path

PROJECT_DIRECTORY = Path(__file__).resolve().parents[3]
BACKEND_DIRECTORY = PROJECT_DIRECTORY / "backend"
