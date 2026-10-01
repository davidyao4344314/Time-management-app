"""Stable existing storage locations, independent of consumer module locations."""

from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]
ARCHIVE_FILE = BACKEND_DIRECTORY / "ai_memory_archive.jsonl"
DURABLE_MEMORY_FILE = BACKEND_DIRECTORY / "ai_durable_memories.json"
