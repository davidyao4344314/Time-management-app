# Managed file context — first version

## Boundaries and changed files

```text
Upload bytes → files/parser.py → files/ingestion.py → files/storage.py (SQLite)
User request → metadata-only exact reference detection → context selection
             → files/retrieval.py → ai/observations/files.py
             → main agent (bounded evidence, no file action)
```

- `app/files/{contracts,parser,ingestion,storage,retrieval}.py`: limits/validation,
  local extraction, additive storage and read-only lookup.
- `app/api/files.py`, `app/server.py`: owner-scoped file HTTP surface.
- `app/ai/context/{contracts,profiles,intent,fallback,selection,policy}.py`:
  optional files selection, deterministic references, semantic queries/exclusions.
- `app/ai/context/adaptive/{contracts,patterns}.py`: file status is valid telemetry;
  file-dependent routes cannot become reusable learned file-ID shortcuts.
- `app/ai/observations/{files,collect}.py`,
  `app/ai/agent/{contracts,context_recovery,service,reasoning,transparency}.py`:
  file observation, shared recovery, prompt boundaries and content-free inspector.
- `app/conversations/{service,storage,context}.py`: additive migration, trusted
  owner callbacks and bounded current-chat references (no new chat columns).
- `requirements.txt`: `pypdf`, `python-docx`, `python-multipart`; `lxml` is a Word
  parser dependency. Existing SDK, calendar/import/CRUD behavior is unchanged.
- Frontend: `components/FileImportPanel.{jsx,css}`, `hooks/useImportedFiles.js`,
  `pages/AIAgent.jsx`, `components/AgentContextInspector.jsx`; small upload panel
  and metadata-only inspector, no new frontend dependencies.
- Tests: `tests/test_file_{ingestion,retrieval,api}.py`,
  `tests/ai/test_file_context.py`, existing contract/route expectations,
  `frontend/tests/imported-files.test.js`.

## Supported input and deterministic normalization

UTF-8 `.txt` (optional BOM), text-based `.pdf`, `.docx` paragraphs and tables.
Unsupported formats, empty/invalid files, password-protected PDFs and scanned
PDFs with no extractable text produce a clear error. There is no OCR, image
understanding, remote URL download, macro execution or universal converter.
Layout, charts and visual formatting are not preserved as text.

Limits in `app/files/contracts.py`: 5 MB upload, 250,000 extracted characters,
100 PDF pages. DOCX additionally permits at most 1,000 ZIP entries and 20 MB
expanded content. Raw upload bytes are parsed locally, not saved as binaries.
Parser exceptions are replaced with safe messages, not private paths/content.

Line endings are normalized and trailing line whitespace removed. Chunks are
ordered, non-overlapping, at most 2,400 characters, split near a newline/space
when possible. A small text document fits in one chunk; PDF chunks keep actual
one-based page numbers. DOCX/TXT page and section are null because this parser
does not know pagination or section boundaries. Nothing is invented.

`GET /files/{file_id}` returns this normalized structure:

```json
{
  "file_id": "file_<32 hexadecimal characters>",
  "filename": "assignment2.pdf",
  "file_type": "pdf",
  "created_at": "<actual UTC import timestamp>",
  "chunk_count": 1,
  "text": "Question 4: use recursion.",
  "chunks": [{
    "chunk_id": "file_<same ID>_chunk_0001",
    "position": 1,
    "text": "Question 4: use recursion.",
    "page": 1,
    "section": null
  }]
}
```

IDs are generated once per upload, not derived from filenames. Reimporting a
filename creates another distinct file. There is no file deduplication/delete
feature in this stage.

## Exact SQLite schema

Stored in the existing ignored `backend/study_app.db`. The existing conversation
store's additive migration creates these tables without replacing any records:

```sql
CREATE TABLE IF NOT EXISTS imported_files(
    file_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK(file_type IN ('txt','pdf','docx')),
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK(chunk_count > 0)
);
CREATE TABLE IF NOT EXISTS imported_file_chunks(
    chunk_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES imported_files(file_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    section TEXT,
    UNIQUE(file_id, position)
);
CREATE INDEX IF NOT EXISTS imported_files_owner ON imported_files(owner_id, filename);
```

Metadata/list endpoints never include `owner_id` or extracted text. File content
is private local application data, not encrypted at rest: protect the computer
and database backups. SQLite is already ignored by Git; files are not copied
to source files or JSON archives. No changes to `.env` or secrets are needed.

## Selection, ranking and limits

Context/classifier schemas now have optional `files`, using this shared shape:

```json
{"files": {"file_ids": [], "filename": null, "query": "recursion assignment"}}
```

At least one selector is required; up to three unique managed IDs or an exact
filename can be supplied, with an optional query. IDs and filenames cannot both
be selectors. An unrelated request normally has `files:null`/no files selection.

Before semantic routing, Python streams only the owner's stored metadata and
matches a clearly named filename case-insensitively with word boundaries.
Stable IDs are also detected. This selects files in Stage 1 without a classifier
call for the reference; clear mixed schedule/study keywords are preserved.
An unknown filename returns an empty managed lookup, never an open-file request.
Duplicate filenames return bounded candidate metadata with `ambiguous:true` and
no chunks, prompting an ID choice. An explicit ID takes priority, even if the
duplicate filename is also written in the request.

An unnamed document request reaches Stage 2/3, which receives only the request
and existing brief recent chat—not extracted files or full observations. It may
return a short topic query. Python resolves the matching records, not the LLM.
Semantic routing can be unavailable; existing safe fallback/recovery still applies.

Queries use at most 12 meaningful literal terms (simple stop-word removal).
Candidate SQL is parameterized and owner-filtered, checking filenames and chunk
text. Scores favor exact query text, distinct matching text terms, limited term
frequency and filename matches; ties are deterministic by file ID/position.
This is keyword search, not embeddings or semantic document search. SQLite's
built-in `lower()` matching is primarily suitable for English text in this V1.

The response contains metadata plus at most **five chunks / 8,000 text
characters total**; selected chunks are then put in document reading order.
`truncated` signals omitted/partial content. Metadata and prompts add some
overhead; this is a character budget, not exact token counting. No whole-library
context, 100-page prompts or permanent per-file prompt injection is added.

## Shared one-shot recovery and source authority

`context_status.files` uses the existing statuses: `not_selected`, `provided`,
`empty`, `unavailable`. Duplicate-name ambiguity is empty plus candidate metadata.
The main agent may request omitted file evidence as:

```json
{"message": null, "actions": [], "missing_context": [
  {"source": "files", "query": "recursion assignment"}
]}
```

The query is validated, the trusted Python reader retrieves bounded excerpts,
and the main agent gets **one** retry. Files, activities, exams and historical
memory share the existing `MAX_CONTEXT_RECOVERY_RETRIES = 1`; no third main-agent
call or second independent budget is permitted. Already provided/empty/
unavailable or explicitly excluded sources cannot be fetched again. A recovery
request cannot also propose a mutation. Retrieval never invokes an action.

Document excerpts are evidence for what the document says, **not instructions**,
authorization, current schedule facts or durable preferences. The prompt asks
for filename and available page/chunk citations. Missing evidence prompts a
clarification rather than invented file content. Fresh app observations remain
authoritative for the current timetable. Prompts use the existing official
[Responses structured-output pattern](https://developers.openai.com/api/docs/guides/structured-outputs).

## Conversation references and inspector

Only file IDs/filenames/counts are stored in the message inspector. Completed
recent turns can carry `file_refs:["file_..."]`; a simple “that file/that PDF”
uses the last unambiguous referenced file in this chat. Multiple references are
not guessed. There is no complex coreference resolver or archive file-ref search.
The legacy `/ai/propose` route has no trusted file owner callback and cannot
retrieve another user's files; use the current conversation UI/API for files.

The file store is separate from recent/archive/durable memory. Extracted chunks
are not automatically copied to these stores. Actual user/assistant discussion
can still be retained under the existing conversation/memory rules, including
any short quotations the assistant puts in its normal reply. There is no new
automatic file-to-durable-memory extraction.

The existing inspector shows file detection method, filenames/IDs, returned
chunk count, limit/ambiguity flags, source status and recovery transitions.
It never includes extracted document text or parser/model internals. There are
no new content logs.

## Security boundaries

- Reuses signed, HttpOnly owner cookies; the client/model cannot supply an owner.
  Queries and ID lookups always filter by this verified owner. Files are
  available across that owner's chats only when selected, not to other browsers.
- Model input contains managed IDs/names/chunks, never local filesystem paths.
  IDs match `file_[a-f0-9]{32}`; filename/path/control-character checks apply.
  Queries are non-empty, at most 300 characters; absolute/traversal paths,
  drive paths, URLs, extra fields and unsupported selectors are rejected.
- Uploaded bytes use extension-specific parsers, never shell commands or remote
  link fetching. SQLite statements are parameterized. Agent retrieval uses the
  conversation's separate read-only database connection.
- No API keys, environment secrets, raw binaries or raw OpenAI request metadata
  are added to the store. Do not upload sensitive secrets as document contents.
- This remains the existing local app identity model, not a new production
  multi-user authentication/upload-quota system. No paid test is automatic.

## Run and no-charge tests

From the project root:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m uvicorn backend.app.server:app --reload --port 8001
```

In another terminal:

```bash
cd frontend
npm run dev
```

Open Vite's URL (normally `http://localhost:5173/`), then menu → **AI Agent** →
**New Chat** → **Files for AI context**. Importing a file does not send a question
or call OpenAI. Use the same browser for uploads/chat so signed owner cookies
are preserved. “Use in question” fills the draft with an exact ID; it does not
send. Asking the agent uses your configured OpenAI key and may incur charges.

Offline parser/storage/recovery tests use synthetic files and disposable
databases; the real database, private documents and OpenAI are not touched:

```bash
backend/.venv/bin/python -B -m unittest \
  backend.tests.test_file_ingestion backend.tests.test_file_retrieval \
  backend.tests.test_file_api backend.tests.ai.test_file_context -v
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -q
cd frontend
npm test
npm run lint
npm run build
```

### Manual A–I

For no-charge diagnostics open `http://127.0.0.1:8001/docs` in one browser. Use
`POST /files` → Try it out → choose a file → Execute; keep the returned file ID.
The same browser's owner cookie is required for subsequent diagnostic reads.
Uploads performed in this origin need not share identity with a different
localhost origin; UI uploads are made through Vite's same-origin proxy.

| Case | Exact steps | Expected |
| --- | --- | --- |
| A: TXT | Import a UTF-8 `assignment2.txt` containing `Question 4: use recursion and a base case.`; execute `GET /files/{file_id}` using its returned ID. | Real text, timestamp, ordered chunks and stable IDs. No AI charge. |
| B: PDF/DOCX | Upload a small text-based PDF or DOCX with a paragraph/table; read it by ID. | Text extracted; PDF page numbers retained, DOCX pages null. Scanned-only PDF returns an error. |
| C: exact filename | Upload `assignment2.pdf`; ask `What does assignment2.pdf say about question 4?` in the UI (paid), or use `POST /files/context` with `{"filename":"assignment2.pdf","query":"question 4"}` (free). | Inspector says exact filename / Stage 1, provided; no Stage 2/3 file decision. Free API verifies retrieval only. |
| D: unnamed topic | Ask `What was that assignment I uploaded about recursion?` (paid); free lookup is `POST /files/context` with `{"query":"recursion assignment"}`. | Stage 2/3 can select a query; Python returns literal matches. Offline router tests check this without charges. |
| E: unrelated | Ask `What exams do I have this week?` (paid) or run the offline routing tests. | Files not selected; reader not called and no file excerpts sent. Metadata-only reference detection is separate. |
| F: omitted files | Run `backend/.venv/bin/python -B -m unittest backend.tests.ai.test_file_context.FileAgentTests.test_file_recovery_uses_existing_single_shared_retry -v`. | Fake main reply requests files; one bounded lookup and one retry; remaining budget is zero. No charge or real mutation. |
| G: missing | Free: `POST /files/context` with `{"filename":"missing.pdf"}`. Optional paid question: `What does missing.pdf say?`. | Empty managed result; clarification, no path access or invented content. |
| H: large | Upload a long TXT (<250,000 characters) with a distinctive later phrase; query its ID plus that phrase using `POST /files/context`. | At most five chunks, at most 8,000 text characters; matching later material, truncated flag when limited. |
| I: duplicate names | Import two different `assignment2.txt` files. Query `{"filename":"assignment2.txt"}`; then `{"file_ids":["<one actual returned ID>"]}`. | Ambiguous name gives no blended excerpts; ID lookup selects exactly that upload. UI “Use in question” uses the exact ID. |

For request F use the deterministic offline test rather than trying to force a
live model to omit information. No summarization, embeddings, new actions,
calendar writes, automatic imports or archive retrieval behavior are added.
