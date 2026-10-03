# Conversations and memory

The AI Agent now stores multiple chats in the existing `backend/study_app.db`.
New Chat creates an empty conversation. Select an existing chat to reopen its
persisted messages. The URL's `chat` parameter restores the selection after
refresh; access still requires the signed local owner cookies.

## Storage and identity

`conversations` stores owner, title, timestamps, status and memory-sharing choice.
`conversation_messages` stores ordered messages, request IDs, completion state,
validated proposals and separate inspector metadata. `conversation_summaries`
stores an optional local summary and its exact message boundary.
`conversation_memory_exports` stores receipts for archive handoff.

Database migrations only add tables. Activities, exams and imports are preserved.
The previously tracked database files are kept locally but removed from the Git
index. `.env`, SQLite runtime files and archive/durable stores remain ignored.
Old database contents remain in earlier Git commits; this change does not rewrite
history. Do not force-add private runtime files.

Owner identity is a signed local browser/profile identity, not a user-account
system. Clearing cookies loses that identity. Conversation IDs alone authorize
nothing. A valid legacy browser cookie retains its owner identity and links only
that verified session as **Previous conversation**. Dated recent turns still in
RAM can be copied once. Legacy archives remain available under their original
identity when that chat's sharing is enabled; compressed summaries are never
presented as reconstructed verbatim messages. Undated/lost recent turns are not
invented. Other legacy sessions are not assigned to the current owner.
The old `/ai/propose` endpoint remains available with its original recent-memory
behavior. New chat requests use SQLite, not that RAM deque.

## API

- `POST /conversations` — create `{ "title": null }` (title optional).
- `GET /conversations` — this owner's latest 100 chats.
- `GET /conversations/{id}/messages?before=...&limit=50` — paginated history.
- `POST /conversations/{id}/messages` — `{ "request_id": "UUID", "message": "..." }`.
- `PATCH /conversations/{id}/settings` — `{ "memory_sharing_enabled": true }`.
- `POST /conversations/{id}/memory/export` — retry eligible archive exports.
- `POST /conversations/{id}/summary` — explicitly update a local summary.

Completed request retries return the saved response without another model call.
Pending requests return pending. Failed requests remain failed; sending a new
request requires a new ID. Only one request per chat may be pending. Requests
interrupted for more than 20 minutes are marked failed during explicit service
maintenance; no paid call is automatically restarted.

The transcript survives model errors and backend restarts. A crash after an
external response but before local persistence cannot guarantee recovery of that
response; the application does not claim otherwise. Aborting a browser request
does not guarantee cancellation of an already-running backend model request.

## Context

Normal requests include bounded recent completed turns from this chat, optional
local summary, the new message and only routed activity/exam observations.
The configured recent-turn limit defaults to five (5–100); an additional 16,000
character budget limits whole turns. This is a character budget, not an exact
token count. The current message is never silently truncated.

The existing three-stage router may select `memory.scope = current_chat` or
`global`. Local lookups search this chat's persisted completed messages. Global
lookups search only opted-in chats owned by the signed profile, using existing
raw/compressed/durable readers and a combined five-result/8,000-character limit.
Current activity/exam facts override historical schedule claims. Proposed actions
are still proposals only; no execution or approval workflow was added.

Examples: “What did I just say?” uses recent chat context. “Earlier in this chat,
what did we discuss about COMPSCI?” can look up local messages. “What did we
decide last month?” can request global memory. “What should I study tonight?”
uses current activities and exams without automatically loading global history.

## Global promotion

Memory sharing is off for new chats. When enabled, completed turns outside the
configured recent window are handed to the existing archive with stable UUIDs,
original timestamps and conversation/owner provenance. Export receipts and
archive source references prevent duplicate exports after interruption, even
after raw rows have been compacted. Disabling sharing excludes the chat from
global retrieval and future exports; it does not delete previously stored data.

The existing staged classification, protection, summarization, persistence and
durable extraction remain separate maintenance tools. They are not run as paid
jobs on every message. Exporting a turn does not assert it is a durable fact.
Compaction does not remove the SQLite transcript.

## Optional local summary

Click **Summarize older messages** to request a summary. This may incur a paid
OpenAI call. The backend requires at least ten newly uncovered completed turns
outside the recent window. It processes up to twenty turns and 24,000 input
characters, and validates at most 1,600 summary characters. No calls occur below
the threshold. Original messages are always retained. Failed summary calls leave
the previous valid summary intact. A summary is not used if increasing the
recent limit would duplicate its covered messages. Interrupted summary jobs can
be requested again after five minutes; they are not automatically retried.

## Test without charges

From the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.test_conversations backend.tests.test_chat_summary -v
```

These tests use temporary databases, isolated archive files and mocked model
responses. They verify owner/chat isolation, persistence, failure handling,
retry identity, opt-in global search, export crash recovery, summary coverage and
preservation of original messages.

## Manual test

1. Run the backend on port 8001 and the frontend with `npm run dev`.
2. Open AI Agent → New Chat. Send a message, then a follow-up.
3. Create another chat. It starts empty; switch back to restore the first chat.
4. Refresh and restart the backend. Messages should still be present.
5. Leave sharing off: other chats cannot retrieve this chat's archive.
6. Enable sharing, complete more than the recent-turn limit, then ask about that
   topic in another chat. Expand the inspector to see actual retrieval/provenance.
7. After at least fifteen completed turns with a five-turn window, click Summarize
   older messages. Continue the chat and verify the inspector lists its summary.
8. A proposed add_activity should remain display-only; inspect Calendar to verify
   no automatic activity insertion.

Live messages and summaries can incur OpenAI charges. No live calls are required
for the automated checks above.
