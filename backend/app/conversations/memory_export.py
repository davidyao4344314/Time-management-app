"""Retry-safe handoff of eligible completed chat turns to the existing archive."""
import json
from uuid import UUID, uuid5

from backend.app.ai.config import get_max_recent_turns
from backend.app.ai.memory import archive_store
from backend.app.ai.memory.selection import report_archive_size
from backend.app.conversations import storage


migrate = storage.migrate_memory_exports


def export_eligible_turns(connection, owner_id, conversation_id):
    chat = storage.require_conversation(connection,conversation_id,owner_id)
    migrate(connection)
    if not chat['memory_sharing_enabled']:
        return {'exported':0}
    rows = storage.export_candidates(connection, conversation_id, owner_id, get_max_recent_turns())
    exported = 0
    for user,proposal,timestamp,request_id in rows:
        identifier = str(uuid5(UUID(conversation_id),request_id))
        if not storage.reserve_memory_export(connection, conversation_id, request_id, identifier):
            continue
        archive_store.append_archived_turn(conversation_id,
            {'timestamp':timestamp,'user':user,'assistant':json.loads(proposal)},turn_id=identifier,owner_id=owner_id)
        # If the process stops before this receipt, the next append detects the stable ID.
        storage.complete_memory_export(connection, conversation_id, request_id)
        exported += 1
    if exported:
        report_archive_size()
    return {'exported':exported}
