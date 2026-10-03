"""Verified legacy chat adoption; all writes go through conversation storage."""
from backend.app.conversations import storage
from backend.app.ai.memory import archive_store, recent


def link_legacy_chat(connection, owner_id, legacy_id):
    if owner_id != legacy_id or storage.conversation_exists(connection, legacy_id):
        return
    turns = recent.get_recent_turns(legacy_id)
    has_archive = next(archive_store.iter_archive_records(session_id=legacy_id), None) is not None
    if turns or has_archive:
        storage.insert_legacy_conversation(connection, owner_id, legacy_id, turns)
