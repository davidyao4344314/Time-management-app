"""Owner-scoped SQLite learning storage. No model, observations or HTTP calls."""

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.ai.context.adaptive.contracts import RoutingEvent, RoutingLabel, PatternApproval
from backend.app.infrastructure.privacy import redact_secrets


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate(connection):
    with connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS routing_events(
            event_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            request_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_json TEXT NOT NULL,
            UNIQUE(owner_id, conversation_id, request_id)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS routing_labels(
            label_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES routing_events(event_id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            label_json TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS routing_patterns(
            owner_id TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            pattern_id TEXT NOT NULL,
            pattern_json TEXT NOT NULL,
            PRIMARY KEY(owner_id, scope_key, pattern_id)
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS routing_owner_time ON routing_events(owner_id, timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS routing_event_labels ON routing_labels(event_id)")


def _require_chat(connection, owner_id, conversation_id):
    if connection.execute("SELECT 1 FROM conversations WHERE owner_id=? AND conversation_id=?",
                          (owner_id, conversation_id)).fetchone() is None:
        raise ValueError("Conversation is not owned by this user.")


def clean_text(text):
    """Routing examples need no private feed URLs or API keys."""
    return re.sub(r"(?:https?|webcal)://\S+", "[redacted URL]", redact_secrets(text), flags=re.I)


def record_event(connection, value):
    event = RoutingEvent.model_validate(value)
    _require_chat(connection, event.owner_id, event.conversation_id)
    event.pattern = clean_text(event.pattern)
    if event.request_excerpt is not None:
        event.request_excerpt = clean_text(event.request_excerpt)
    clean = RoutingEvent.model_validate(redact_secrets(event.model_dump()))
    with connection:
        cursor = connection.execute("""INSERT INTO routing_events VALUES(?,?,?,?,?,?)
            ON CONFLICT(owner_id, conversation_id, request_id) DO NOTHING""",
            (clean.event_id, clean.owner_id, clean.conversation_id, clean.request_id,
             clean.timestamp, clean.model_dump_json()))
    return cursor.rowcount == 1


def event_by_id(connection, owner_id, event_id):
    row = connection.execute("SELECT event_json FROM routing_events WHERE owner_id=? AND event_id=?",
                             (owner_id, event_id)).fetchone()
    if row is None:
        raise ValueError("Routing event not found for this owner.")
    return RoutingEvent.model_validate_json(row[0])


def record_label(connection, owner_id, event_id, value, *, invalidate_pattern=None):
    event_by_id(connection, owner_id, event_id)
    label = RoutingLabel.model_validate(redact_secrets(value))
    identifier = uuid4().hex
    with connection:
        connection.execute("INSERT INTO routing_labels VALUES(?,?,?,?,?)",
                           (identifier, event_id, owner_id, now_iso(), label.model_dump_json()))
        if invalidate_pattern is not None:
            for scope_key, value in list(connection.execute(
                    "SELECT scope_key, pattern_json FROM routing_patterns WHERE owner_id=? AND pattern_id=?",
                    (owner_id, invalidate_pattern))):
                approval = PatternApproval.model_validate_json(value)
                if not label.complete or approval.selection != label.selection:
                    approval.suspended = True
                    connection.execute("UPDATE routing_patterns SET pattern_json=? WHERE owner_id=? AND scope_key=? AND pattern_id=?",
                                       (approval.model_dump_json(), owner_id, scope_key, invalidate_pattern))
    return identifier


def load_eligible_evidence(connection, owner_id, conversation_id, *, limit=5000):
    """Recheck sharing on every read; newest label supersedes older labels."""
    _require_chat(connection, owner_id, conversation_id)
    rows = connection.execute("""SELECT e.event_json, l.label_json, l.label_id
        FROM routing_events e JOIN conversations c ON c.conversation_id=e.conversation_id
        LEFT JOIN routing_labels l ON l.rowid=(
            SELECT MAX(x.rowid) FROM routing_labels x WHERE x.event_id=e.event_id AND x.owner_id=e.owner_id)
        WHERE e.owner_id=? AND c.owner_id=?
          AND (e.conversation_id=? OR c.memory_sharing_enabled=1)
        ORDER BY e.timestamp DESC, e.event_id DESC LIMIT ?""",
        (owner_id, owner_id, conversation_id, max(1, min(limit, 5000))))
    return [{"event": RoutingEvent.model_validate_json(event),
             "label": RoutingLabel.model_validate_json(label) if label else None,
             "label_id": identifier} for event, label, identifier in rows]


def save_pattern(connection, owner_id, scope_key, pattern_id, value):
    _require_chat(connection, owner_id, scope_key)
    with connection:
        connection.execute("""INSERT INTO routing_patterns VALUES(?,?,?,?)
            ON CONFLICT(owner_id, scope_key, pattern_id) DO UPDATE SET pattern_json=excluded.pattern_json""",
            (owner_id, scope_key, pattern_id, json.dumps(redact_secrets(value))))


def load_pattern_states(connection, owner_id, conversation_id):
    _require_chat(connection, owner_id, conversation_id)
    return {identifier: json.loads(value) for identifier, value in connection.execute(
        "SELECT pattern_id, pattern_json FROM routing_patterns WHERE owner_id=? AND scope_key=?",
        (owner_id, conversation_id))}


def reset_owner_learning(connection, owner_id):
    """Delete learning records only; conversations and planner rows are untouched."""
    with connection:
        connection.execute("DELETE FROM routing_labels WHERE owner_id=?", (owner_id,))
        connection.execute("DELETE FROM routing_events WHERE owner_id=?", (owner_id,))
        connection.execute("DELETE FROM routing_patterns WHERE owner_id=?", (owner_id,))


def reserve_audit(connection, owner_id, conversation_id, request_id, day, *, limit):
    """Reserve a paid audit slot atomically, including failed attempts in the cap."""
    _require_chat(connection, owner_id, conversation_id)
    scope = "audit:" + day
    identifier = conversation_id + ":" + request_id
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute("SELECT 1 FROM routing_patterns WHERE owner_id=? AND scope_key=? AND pattern_id=?",
                                      (owner_id, scope, identifier)).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM routing_patterns WHERE owner_id=? AND scope_key=?",
                                   (owner_id, scope)).fetchone()[0]
        allowed = bool(existing) or count < limit
        if allowed and not existing:
            connection.execute("INSERT INTO routing_patterns VALUES(?,?,?,?)",
                               (owner_id, scope, identifier, '{"kind":"audit_reservation"}'))
        connection.commit()
        return allowed
    except Exception:
        connection.rollback()
        raise
