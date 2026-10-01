"""Stable existing storage locations, independent of consumer module locations."""

from backend.app.infrastructure.paths import BACKEND_DIRECTORY


ARCHIVE_FILE = BACKEND_DIRECTORY / "ai_memory_archive.jsonl"
DURABLE_MEMORY_FILE = BACKEND_DIRECTORY / "ai_durable_memories.json"
