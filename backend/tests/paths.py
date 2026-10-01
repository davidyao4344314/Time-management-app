"""Stable test locations after test files move into feature folders."""

from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_DIRECTORY = BACKEND_DIRECTORY.parent
