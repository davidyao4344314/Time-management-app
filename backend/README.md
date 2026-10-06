# Study Planning App

This README explains how to run the project and describes the backend as it
currently works. The AI agent can **propose** an activity, but cannot yet save
an AI-proposed activity.

## Stage 8: Action Layer structure

`ai/actions` now contains generic proposal/result contracts, explicit tool discovery,
a minimal router, temporary approve/reject lifecycle, an approval-gated executor
and a response-planning interface. This is **structure only**: the default
`add_activity` registration reuses the existing schema but has no executable
handler. Normal chat/API responses are unchanged; no approval UI or execution
endpoint is connected, and no planner data is written by this layer.

See [Action Layer contracts, boundaries and offline tests](ACTIONS.md) for the
file tree, lifecycle, dependency direction and fake-tool test commands.

## Multi-conversation AI chat

AI Agent now supports New Chat, persisted message history and switching between
conversations. Recent context belongs only to the selected chat. Global memory
sharing is opt-in; optional local summaries preserve the original transcript.
See [Conversations and memory](CONVERSATIONS.md) for the API, storage boundaries,
migration details and no-charge tests. The older `/ai/propose` route remains a
compatibility path with its original recent-memory behavior.

## Imported files as AI context (V1)

The AI Agent page has a small **Files for AI context** panel. Import UTF-8 TXT,
text-based PDF or DOCX files there, then mention a filename in a question or
choose **Use in question** to use its stable ID. Importing and the diagnostic
file APIs are local and make **no OpenAI request**. Sending an AI question still
uses your configured API key and may incur charges.

Files are a separate read-only observation source, not an agent action or
conversation/global memory. Exact file references bypass semantic file routing;
unnamed documents can be selected by Stage 2/3. Retrieval sends at most five
chunks and 8,000 excerpt characters. It shares the existing one-shot context
recovery budget. Duplicate names require a specific ID, not an arbitrary choice.

See [File ingestion, storage, retrieval and tests A–I](FILES.md) for the exact
schemas, endpoints, privacy boundaries, limitations and no-charge test commands.

## Run the API

From the project root, install dependencies into the existing backend virtual
environment and start FastAPI:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m uvicorn backend.app.server:app --reload --port 8001
```

Open `http://127.0.0.1:8001/docs` for the API documentation. Press `Ctrl+C` in
the terminal to stop the server. The FastAPI `app` is in
`backend/app/server.py`. The old `backend.fastapi_test:app` command remains
compatible. `backend/app/cli.py` is the interactive Python program, not the
ASGI app; the old `backend/app/main.py` script forwards to it. The frontend's Vite `/api` proxy targets port 8001.

## Run the frontend

Open a second terminal and, from the project root, run:

```bash
cd frontend
npm install
npm run dev
```

`npm install` is only needed the first time or after dependencies change. Open
the local URL printed by Vite, usually `http://localhost:5173/`. Keep the
backend running in the first terminal for features that use the API. Press
`Ctrl+C` in the frontend terminal to stop Vite.

## Backend folder structure

Related code is grouped under `backend/app`:

```text
backend/
├── app/
│   ├── server.py             # FastAPI app: mounts feature routers
│   ├── cli.py                # Existing interactive planner program
│   ├── database.py           # Existing SQLite connection/schema setup
│   ├── conversations/        # Persistent chats, local context, summaries, export receipts
│   ├── files/                # Local TXT/PDF/DOCX parsing, SQLite storage, bounded reads
│   ├── ai/
│   │   ├── config.py         # Local API key/model/memory-limit settings
│   │   ├── agent/            # Agent coordination, reasoning and contracts
│   │   ├── context/          # Stage 1/2/3 routing + opt-in adaptive evidence
│   │   ├── observations/     # Compact activity/exam/Screen Time formatters
│   │   ├── actions/          # Proposal/approval/execution skeleton; no real tool handlers
│   │   ├── memory/           # Recent, archive, compaction and durable memory
│   │   └── compat/           # Temporary multi-owner legacy adapters
│   ├── planner/              # Activities, exams, calendar and activity service
│   ├── screen_time/          # Daily summary storage
│   ├── integrations/         # Shared iCal parser, Canvas and UoA importers
│   ├── api/                  # AI, activities, exams, calendar, imports, helpers
│   ├── infrastructure/       # Stable paths, file locking and privacy utilities
│   └── dev/                  # Explicit offline/debug and receipt-test commands
├── tests/
│   ├── ai/                   # Agent/API checks, plus memory/ stage tests
│   ├── planner/              # Activity service, recurrence and metadata checks
│   ├── integrations/         # Import and UoA range checks
│   └── screen_time/          # In-memory summary-storage checks
├── .venv/
├── requirements.txt
├── README.md
└── ARCHITECTURE.md
```

See [Backend architecture](ARCHITECTURE.md) for detailed ownership and import
rules. The reorganized files do not add new behavior. API paths, prompts,
recurrence and import rules are unchanged.

Old flat modules and former package paths remain small compatibility wrappers,
not second implementations. Existing scripts and the old server command still
work. New code should use the grouped modules, for example:

```python
from backend.app.planner.activities import add_activity
from backend.app.ai.memory.recent import get_recent_turns
from backend.app.integrations.uoa_timetable_import import get_uoa_timetable_events
```

The database, project-root `.env`, archive and durable-memory files stay in
their existing locations. No real records or secret values are moved.

To run the existing interactive Python program from the project root:

```bash
backend/.venv/bin/python -m backend.app.cli
```

## AI study-planning workflow: implemented

```text
POST /conversations/{id}/messages with a message and request ID
  -> verify signed owner, save the pending user message
  -> select bounded recent completed turns from this chat (5–100)
  -> choose activity/exam context with the Stage 1/2/3 routing pipeline
  -> build fresh observations and retrieve memory only when selected
  -> send selected context, optional local summary and recent turns to OpenAI
  -> validate a structured message and proposed actions
  -> persist the assistant response; return it without executing actions
```

The API checks for a configured `OPENAI_API_KEY` before calling OpenAI. The key
stays in the backend's local environment configuration; it is not returned in
the proposal. New conversation requests write transcript tables, not planner
activities/exams. The compatibility `/ai/propose` endpoint still reads the
planner database without writing to it.

### Recent conversation memory

A completed turn contains a user message and the assistant's response. New chats
persist their full transcript in SQLite and select 5–100 recent completed turns
for context (default 5, adjustable in AI Settings). A 16,000-character budget
also bounds this window. Oversized turns use literal excerpts (at most 8,000
characters per turn); original SQLite messages remain complete. A separately requested local summary can
cover older turns without deleting them or repeating recent messages.

Global sharing is off by default. Opted-in older completed turns can enter the
Git-ignored archive using idempotent export receipts. Global memory is retrieved
only when selected and only from the same owner's opted-in chats. Failed requests
do not enter completed context. Proposed actions are not completed changes.
See [Conversations and memory](CONVERSATIONS.md) for limits and recovery details.

The compatibility `/ai/propose` route retains its RAM-backed recent turns and
legacy archive behavior. Its recent turns do not survive a backend restart;
SQLite conversation transcripts do.

### Adaptive context selection (opt-in)

The nine adaptive-routing steps are implemented. They improve **context
selection**, not the model's weights or the schedule itself:

```text
completed routing choices / recovery signals
  -> bounded owner-scoped evidence (unconfirmed)
  -> explicit developer/structured-user review
  -> consistent exact-phrase patterns, reviewed Stage 2 examples, reliability statistics

new request
  -> static Stage 1 or eligible, explicitly activated learned phrase
  -> Stage 2 if unresolved (optionally 1–3 confirmed examples)
  -> unchanged Stage 3 if unresolved/unreliable
  -> validated context selection -> fresh observations -> main agent -> proposal only
```

Learning is **off by default**. Configure these optional values in the existing
ignored project-root `.env` (never put a key or private URL in source code):

```dotenv
AI_ADAPTIVE_ROUTING_MODE=observe
AI_ADAPTIVE_STAGE2_EXAMPLES=false
AI_ADAPTIVE_CALIBRATION=false
AI_ADAPTIVE_AUDITS=false
```

Restart FastAPI after changing local configuration. Modes:

| Mode | Behavior |
| --- | --- |
| `off` | Original routing, no new evidence recorded. Invalid mode also disables adaptation. |
| `observe` | Original routing; record completed choices/recovery for later review. |
| `shadow` | Compute learned-pattern matches for inspection; do not change routing or classifier input. |
| `active` | Use explicitly approved, freshly eligible shortcuts. Examples/calibration/audits each require their separate flag. |

The conversation service creates three small learning tables in the **existing**
SQLite database: `routing_events`, `routing_labels`, `routing_patterns`. No
planner columns change. Evidence is keyed by owner/conversation/request, so a
retried completed request is not counted again. Labels are append-only; the
latest review supersedes earlier ones. Requests are bounded to 600 characters;
private URLs/API keys are redacted. Observations, model scratchpads and raw API
metadata are not stored here. The database remains Git-ignored. This is local
private conversation data, not anonymized telemetry.

Evidence from the current chat is eligible. Another chat must belong to the
same signed owner **and** currently allow memory sharing. Sharing is rechecked
on every snapshot; revoking it also removes its evidence/examples from use.
Global memory, current-chat memory and schedule observations remain distinct.
Corrections and rejections use the same sharing rule when suspending learned
patterns: a private source chat can affect only its own pattern approvals.

`ai/context/adaptive/settings.py` defines the conservative thresholds:

- A phrase needs at least **30 complete confirmed reviews**, **97% joint
  context-profile agreement**, and evidence from **3 distinct UTC dates**.
- Statistics use up to the newest **100** unique labeled requests from the
  last **90 days**; the newest supporting evidence must be within **30 days**.
- Full-profile agreement compares activity/exam inclusion and windows, and
  memory selection—not merely the intent label.
  Reviews requiring memory count toward agreement and contradictions, even
  though V1 cannot activate a memory-retrieval shortcut.
- Promotion requires a separate explicit shadow-review approval. V1 learns
  **exact normalized phrases**, preserving date/negation words; it does not
  generate broad keywords, regex rules, or memory-retrieval shortcuts.
- Follow-up dependencies, explicit exclusions, conflicting dates, static-rule
  conflicts and absolute-date phrases cannot be bypassed by learned shortcuts.
- A new contradictory review or rejection suspends an approved rule. Stale or
  insufficient evidence also makes it unusable. A suspended rule requires at
  least **10 new confirmed reviews**, qualifying statistics, and explicit
  reapproval; it never silently re-enables. The 90% demotion floor is weaker
  than the implemented conservative contradiction/97% eligibility guards.
- Stage 2 examples require a complete, explicitly approved classification.
  Selection uses simple topic overlap, not another LLM call. Maximum **3**
  examples, **600 characters per complete example**, **1,800 in total**;
  contradictory examples for the same normalized request are excluded.
- Reliability separates intent confusion from context-selection errors.
  Partial reviews score only reviewed fields. At least **50 full reviews** in
  the same model/prompt/example-pack/source-family/high-confidence bucket are
  needed before agreement below **95%** can escalate to Stage 3. Low-confidence
  outputs are never promoted. Model/policy/example-pack changes start a new
  calibration bucket. These are empirical agreement rates, not probabilities
  returned by the LLM.
- Optional audits sample roughly **1 in 20** matched active shortcuts, with at
  most **5 audit requests per owner per UTC day**. Slots are atomically reserved;
  failed attempts count and retries reuse the same slot. An audit runs normal
  semantic routing and **can incur API cost**. Audits are disabled by default.

Stage 3 disagreement, successful context recovery and syntactically valid
output are **not truth labels**. They are review signals only; self-predictions
never confirm themselves. Current SQLite observations remain authoritative.
Action validation/approval is unchanged, and no proposed action is executed.
The legacy `/ai/propose` path remains nonadaptive; this feature belongs to the
owner-authorized `/conversations/{id}/messages` flow.

#### Local review commands

The developer tool opens an existing database only; it cannot create a second
database or call an LLM. Start the app once to create the learning tables. Supply
the owner and chat IDs from your local development conversation records. The
CLI is a local developer utility, not a public endpoint or an owner-authentication
replacement. Do not publish its private request excerpts.

```bash
backend/.venv/bin/python -B -m backend.app.dev.routing_learning --owner OWNER list --chat CHAT
backend/.venv/bin/python -B -m backend.app.dev.routing_learning --owner OWNER label \
  --event EVENT \
  --selection '{"activities_scope":"tomorrow","include_exams":false,"exam_scope":null,"memory":null}' \
  --fields activities_scope,include_exams,exam_scope,memory
backend/.venv/bin/python -B -m backend.app.dev.routing_learning --owner OWNER patterns --chat CHAT
backend/.venv/bin/python -B -m backend.app.dev.routing_learning --owner OWNER activate \
  --chat CHAT --pattern PATTERN_HASH --confirm-shadow-review
backend/.venv/bin/python -B -m backend.app.dev.routing_learning --owner OWNER metrics --chat CHAT
```

`label` can confirm only selected fields (use a shorter `--fields` list), but
partial reviews cannot promote a shortcut or calibrate the whole profile. To
approve an example, also supply reviewed `--classification` JSON in the existing
`AgentRoutingDecision` format and `--approve-example`; it must agree with the
selection. `reject --event EVENT` withdraws evidence and suspends an associated
rule. `reset --confirm-reset` clears **only that owner's learning tables**, not
chats, activity/exam rows or archives. No natural-language correction is
automatically treated as a complete review.

The existing **How the agent used context** panel displays mode, shortcut use,
review counts, observed agreement, examples used, reliability status and audit
status. It also shows separate activity/exam windows. It exposes no learned
example text, owner IDs, label IDs, prompts or reasoning.

#### Test without API charges

Run from the project root:

```bash
backend/.venv/bin/python -B -m backend.app.dev.adaptive_routing_check
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t .
cd frontend
npm test
npm run lint
npm run build
```

The offline check compares original/shadow/active behavior using synthetic
reviews and a fake classifier; it does not read `.env`, real chats or archives,
open a database, or make an API call. It covers exact/nearby phrases, punctuation,
exclusions, changing dates, follow-ups and audit routing. Unit tests additionally
cover owner isolation, revoked sharing, correction/suspension, budget limits,
model-version buckets and partial evidence. **These tests verify wiring and
guards, not real semantic accuracy or actual cost savings.**

Before enabling `active`, review shadow results and evaluate a separate held-out
set of paraphrases, exclusions, personal-vs-generic questions, independent exam
horizons, memory scopes and follow-ups. Do not train on the held-out labels.
Compare source/window errors, missing-context recovery and classifier-call counts
against the original routing; accuracy must not regress. The existing
`backend.app.dev.stage_two_check` previews cases offline; adding `--llm`
explicitly makes **paid** Stage 2 calls. Live conversational tests also cost money.
No paid evaluation was automatically run for this implementation.

### Archive compaction threshold (Stage 1)

`backend/app/ai/memory/settings.py` defines `ARCHIVE_TURN_THRESHOLD = 100` and
`ARCHIVE_COMPACT_BATCH = 50`. After each turn is appended to the existing
JSONL archive, the backend counts valid archived turn records
across all sessions. `archive_needs_compaction()` returns `True` only when the
count exceeds 100: 100 turns does not need compaction; 101 does. The backend
then logs a warning with the turn count, without printing conversation text.

This is detection only. It does not summarize, delete, or compact archived
turns, change the recent-memory limit, or send archived turns to normal model
requests. To test the boundary cases without changing the real archive or
calling OpenAI, run from the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_archive_compaction -v
```

The tests cover archives of 0, 50, 99, 100, 101, and 150 turns.

### Archive candidate selection (Stage 2)

`backend/app/ai/memory/selection.py` provides
`select_archive_compaction_candidates()`, which uses the Stage 1 threshold. If the
archive exceeds 100 turns, it returns up to 50 archived turns from one session as
`compaction_candidates`, along with candidate/remaining counts and known
timestamp bounds. Dated turns are ordered by their stored completion times;
undated legacy turns use archive file order after dated turns. At 100 archived
turns it selects none. A protected-only oldest chat cannot block later work;
protected prefixes can be skipped for selection without deleting them.
`after_session_id` optionally advances selection to another session, and the
result includes `selected_session_id`. A protected-only archive remains available
for durable extraction. This
function reads only archived turns, not recent in-memory turns. It does not
rewrite the archive.

### Archive candidate protection labels (Stage 2.5)

`backend/app/ai/memory/protection.py` classifies only the Stage 2 candidate
list. `classify_archive_candidate()` labels one complete user/assistant turn;
`classify_compaction_candidates()` groups the batch into `protected`,
`compactable`, and `uncertain`, preserving order and the original archived
record in each result. The result also includes counts for each group.

Case-insensitive phrase rules protect explicit memory requests, long-term
goals or plans, preferences, decisions, requirements, and constraints. Examples
include "remember this", "from now on", "my long-term goal", "we decided",
"this is a requirement", and "do not change". Weak words such as "important",
"goal", and "plan" do not protect a turn on their own; ambiguous turns remain
`uncertain`. Simple one-off explanation questions can be `compactable`.
Both the user message and assistant response are checked, but proposed action
arguments are not treated as conversation text.

Stage 2.5 itself produces **labels only**: it makes no model call and changes
no archive records. Later stages use these labels to decide what may be
summarized and persisted. To test both read-only stages without touching the
real archive or calling OpenAI, run:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_archive_compaction backend.tests.ai.memory.test_ai_archive_protection -v
```

### Resolve uncertain archive candidates (Stage 3)

`backend/app/ai/memory/classification.py` sends only Stage 2.5 `uncertain`
turns to a small OpenAI classification call. Its structured result must label
each candidate `protected` or `compactable` with a compatible category. A
missing key, failed call, or invalid response keeps the affected batch
`protected` rather than risking its removal. This stage does not edit the
archive. Its tests mock OpenAI:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_archive_llm_classifier -v
```

### Summarize compactable turns (Stage 4)

`backend/app/ai/memory/summary.py` summarizes only candidates with final
`compactable` status. It produces short bullets and keywords under the fixed
categories `activities`, `exams_tests`, `study_topics`, `technical_issues`, and
`general`, plus the source-turn refs and time range. It can flag meaningful
`general` bullets for a category review. Protected candidates are excluded.
The result is still in memory; no raw archive turns are removed.

### Review a possible new category (Stage 4.5)

`backend/app/ai/memory/category_review.py` runs a second, small model call
only when Stage 4 flags unresolved `general` items. The model may propose at
most one broad new category. Python checks the name, duplicates/synonyms,
protected-memory categories, and evidence from at least two matching summary
items. If accepted, only those summary bullets move to the new category in
the in-memory result. Rejected bullets stay under `general`; no archive file
is changed at this stage. These tests also mock OpenAI:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_archive_summary backend.tests.ai.memory.test_ai_archive_category_review -v
```

### Persist a compacted summary (Stage 5)

`backend/app/ai/memory/compaction.py` exposes
`persist_compacted_archive(final_result, classified_candidates)`. It accepts
the final Stage 4/4.5 result and the same final classified-candidate list used
to make it. Stage 5 makes **no** model call and does not decide anew which
turns are compactable. It validates the summary, source count and refs, time
range, and each source's final `compactable` status before touching the
archive. Missing, duplicate, ambiguous, or protected source matches abort
without removing raw turns. Only `source_turn_refs` determine what is removed:
unreferenced candidates stay raw, including compactable candidates that were
not included in the summary. Conflicting classifications of the same source
turn also abort the operation.

The existing Git-ignored `backend/ai_memory_archive.jsonl` now supports two
record kinds: raw turns (with `turn` and, for new turns, a UUID `turn_id`) and
`compressed_summary` records. A compressed record contains a distinct UUID
`summary_id`, `created_at`, `period_start`, `period_end`,
`source_turn_count`, categorized summary bullets/keywords,
`source_turn_refs`, and a source fingerprint. Older raw turns without IDs
must match their complete stored record *uniquely*; otherwise Stage 5 stops.
Existing archive search still reads raw turns only—it does not retrieve
compressed summaries yet.

Stage 5 writes and verifies a temporary copy containing the summary while
retaining all raw turns. It then prepares and verifies the final copy with
only the matched raw turns removed. A single most-recent private backup,
`backend/ai_memory_archive.backup.jsonl`, preserves the previous archive
before the atomic replacement. Archive appends and replacement share a stable
lock file. If validation or a write fails, the original archive stays in
place; if post-replacement verification fails, Stage 5 attempts to restore
it. If restoration itself fails, the backup remains for recovery. Archive,
backup, lock, and temporary files are ignored by Git. Retrying the same
source set returns `already_persisted` instead of adding a second summary.
Before replacement and after read-back, Stage 5 checks every retained record
against the original to preserve its content and order, and verifies the new
summary appears exactly once. Failures report which validation or write step
failed; an absent summary or an empty source list returns `nothing_to_persist`.

Stage 5 is implemented but is **not automatically run** when the Stage 1
threshold is crossed, and it has not been run on the live archive as part of
development. To exercise normal success and failure cases A–H safely using
temporary files, run:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_archive_persistence -v
```

### Extract structured durable memory (Stage 6)

`backend/app/ai/memory/durable.py` exposes
`extract_durable_memories(protected_turns)`. Pass only the final protected
entries from Stage 2.5 and Stage 3:

```python
from backend.app.ai.memory.durable import extract_durable_memories

result = extract_durable_memories(
    stage_2_5_result["protected"] + stage_3_result["protected"]
)
```

The result variables above are earlier-stage outputs, not global variables
created by this module. Stage 6 does not automatically run those stages or
load the archive. It rejects compactable/uncertain entries, summaries, raw
unclassified records, recent turns and invalid or duplicated source refs.

The flow is:

```text
Final protected candidate entries
  -> dedicated durable-memory extraction prompt
  -> strict structured output validation
  -> deterministic duplicate comparison
  -> separate atomic durable-memory storage

Original protected raw turns remain unchanged.
```

#### Extraction prompt and allowed types

The dedicated `DURABLE_MEMORY_INSTRUCTIONS` prompt extracts concise,
explicitly established facts or rules likely to matter in future conversations.
It is separate from the study-agent prompt. It prohibits invented goals or
preferences, advice, SQL, tool execution and interpreting an assistant's
proposal as a completed action or agreed decision. A protected turn can
produce several memories, or none. Temporary plans and ordinary debugging
questions do not become permanent preferences just because an earlier stage
conservatively protected them.

The fixed types are `goal`, `preference`, `decision`, `requirement`,
`constraint`, `long_term_plan`, `project_architecture`, `explicit_memory`,
`unfinished_task`, and `other_durable`. Only `status = "active"` is supported;
lifecycle changes are not implemented.

Stage 6 uses the existing OpenAI SDK `responses.parse()` approach with
`DURABLE_MEMORY_MODEL = DEFAULT_AGENT_MODEL`, reasoning effort `none`,
`store=False`, a 60-second timeout and no automatic retries. It reads
`OPENAI_API_KEY` through the existing backend configuration. Requests contain
only protected user/assistant text, source refs and timestamps: no recent
conversation, activity/exam observations, compressed summaries or action
arguments. Different sessions are processed separately in batches of at most
10 turns. Nothing is persisted until every batch succeeds.

The model response has this shape (identifiers below are placeholders):

```json
{
  "memories": [
    {
      "type": "constraint",
      "content": "Agent actions require user approval before execution.",
      "status": "active",
      "source_turn_refs": ["existing-turn-UUID"],
      "source_timestamp": null
    }
  ]
}
```

`{"memories": []}` is valid. Python rejects unknown fields/types, invalid
status, non-list memories, empty content, multiline/code-block content, text
over 320 characters, API keys, duplicate or unsupported refs, and timestamps
that do not match the cited sources. Each response is limited to 50 memories.
These checks validate structure/provenance; they do not independently prove
the model's interpretation is factually correct. Review live extraction
results before adding any later cleanup or retrieval stage.

#### Durable storage and source references

The first successful extraction creates the separate Git-ignored file
`backend/ai_durable_memories.json`. It does not mix durable facts with raw
archive turns or compressed summaries. Its structure is:

```json
{
  "durable_memories": [
    {
      "memory_id": "generated-UUID",
      "type": "constraint",
      "content": "Agent actions require user approval before execution.",
      "status": "active",
      "created_at": "ISO timestamp with timezone",
      "source_timestamp": null,
      "source_turn_refs": [
        {
          "turn_id": "existing-turn-UUID",
          "record_sha256": "original-record-SHA256",
          "session_id": "original-session",
          "timestamp": null
        }
      ]
    }
  ]
}
```

Python creates the memory UUID and creation timestamp and resolves each model
ref to the original source metadata. Existing turn UUIDs are reused. Legacy
turns without IDs are referenced as `legacy:<record_sha256>` in the model
input/output and stored with `turn_id = null` plus the original record's
fingerprint. No permanent list-position IDs or old timestamps are invented.
Each source retains its original timestamp or `null`; `source_timestamp` is
the first non-null timestamp in that memory's source-ref order.

#### Duplicate comparison and safe persistence

Duplicate comparison requires the same memory type and session. It normalizes
Unicode, case, whitespace and terminal punctuation while retaining word order,
negations, numbers and internal punctuation. It also recognizes the specific
equivalent pair "Agent actions require user approval before execution" and
"User approval is required before executing agent actions". This is a
conservative comparison, not general semantic matching or embeddings.

A duplicate keeps its existing ID, content and creation time, and gains any
new source references. Retrying identical extraction does not add another
memory or rewrite an unchanged store. Different browser sessions are not
merged.

Persistence reuses Stage 5's verified temporary-file and atomic replacement
helpers on the separate durable file. A private sidecar lock serializes
writers, and a most-recent backup preserves the previous state before
replacement. Files use private permissions (`0600`); symlink targets and
invalid existing stores are not overwritten. API or validation failures save
nothing. Post-replacement failures attempt restoration and report when
recovery needs attention. Protected raw turns are never read or modified by
Stage 6 itself.

Git ignores the durable store, `backend/ai_durable_memories.json.lock`,
`backend/ai_durable_memories.backup.json`, and the reused temporary-file pattern
`backend/.archive-stage5-*`.

Success returns counts:

```json
{
  "status": "success",
  "input_protected_turns": 12,
  "memories_extracted": 8,
  "memories_created": 6,
  "duplicates_reused": 2
}
```

Empty input or no durable facts returns `nothing_to_extract`, the input count
and `memories_extracted = 0`. Failure returns `failed`, a safe error message,
the input count and `memories_created = 0`.

#### Test Stage 6 safely

From the project root, run the 19 offline tests:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_ai_durable_memory -v
```

Print the A-I examples and their stored structure without an API charge:

```bash
backend/.venv/bin/python -B -m backend.tests.ai.memory.test_ai_durable_memory --examples
```

These use mocked model responses and temporary files. They verify validation
and persistence, not live model classification accuracy. The cases cover:

| Case | Expected result |
| --- | --- |
| A: Remember to ask before changing activities | Approval rule retained as explicit memory or constraint. |
| B: Finish the app before semester ends | Goal. |
| C: One meaningful Git commit per feature | Preference. |
| D: Search archived memory only when needed | Decision. |
| E: LLM must never execute SQL directly | Constraint. |
| F: Maybe study Python tonight | No durable memory. |
| G: Why is this loop broken? | No durable memory. |
| H: Long-term goal plus persistent preference | Two extracted memories; the demo reuses the earlier B/C records. |
| I: Approval rule phrased differently | Existing memory reused, with another source ref. |

For an optional **paid live OpenAI test**, configure the existing backend key
and run:

```bash
backend/.venv/bin/python -B -m backend.tests.ai.memory.test_ai_durable_memory --live
```

The live demo tests the same A-I requests, including a seed for the duplicate
case. Inspect the printed types/content and counts; model wording can vary,
and the deterministic duplicate comparison is intentionally limited. Both
demos use disposable storage and leave the real archive and durable store
unchanged. Development verification passed all 173 backend tests without
making a live Stage 6 API call.

Stage 6 is an explicit backend helper, not an automatic compaction step or a
normal agent-request feature. No durable-memory retrieval, frontend UI,
protected-turn deletion, lifecycle management or new endpoint is implemented.

### Developer trace: fake archive-memory pipeline

The standalone `backend/app/dev/memory_debug.py` command traces Stages 1-6 using
16 fake, timestamped turns with stable UUIDs. It calls the existing production
functions; it does not implement a second memory pipeline. Run it in its own
terminal process, not inside the API server, because its temporary module
patches are scoped to this standalone debug process.

From the project root, the default run makes **no LLM calls**:

```bash
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage all --skip-llm
```

It prints the fake archive, real Stage 1/2/2.5 results and clearly marks
model-dependent stages as skipped. It does not fabricate model results.
To inspect the full pipeline with **paid OpenAI calls**, opt in explicitly:

```bash
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage all --llm
```

Stage 5 defaults to dry-run: it uses the production summary/source validators,
matching and retained-record checks to show the summary and exact raw turns
that would be removed. Stage 6 runs production extraction/validation but
merges into an in-memory fake store. Neither stage writes persisted memory in
default dry-run mode. To exercise actual persistence in disposable fake files:

```bash
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage all --llm --write-fake
```

All modes redirect archive and durable-memory paths to a fresh temporary
directory before calling memory functions. The fixture is initialized there;
dry-run verifies it was not subsequently changed. Optional fake writes and
their backups/locks remain inside that directory and are discarded on exit.
The real archive/durable files are never read or written. Recent memory,
SQLite, frontend code and production thresholds are unchanged. Debug-only
threshold/batch values are 10/14 so the 16-turn fixture exercises the pipeline
and leaves two newer turns unselected; production values stay 100/50.

Individual stages are supported with `--stage 1`, `2`, `2.5`, `3`, `4`, `4.5`,
`5` or `6`. Necessary earlier dependencies run first. Stage 6 omits the
unrelated summary/persistence stages. For example:

```bash
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage 2.5 --skip-llm
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage 6 --llm
```

The fixture includes activity and exam queries, recursive-list explanations,
FastAPI debugging, an approval memory request, an app-completion goal, a
commit preference, a Python recurrence decision, tentative memory work,
internship/CV topics, thanks/resolved discussion, an approval constraint and
a repeated recursion topic. Each turn is printed before classification.
The career examples may justify a dynamic category; acceptance depends on
the actual model output and existing Python checks, not a hardcoded outcome.

Stages 3, 4, 4.5 and 6 can make paid calls under `--llm`; Stage 4.5 calls only
when enough unresolved general items require review. Each uses its existing
dedicated prompt and smallest relevant input: uncertain turns, compactable
turns, flagged summary bullets or protected turns respectively. No app
observations or recent history are included. Failures remain visible in the
trace and retain the existing production safeguards.

Inspect the selected/unselected IDs, protection rules, Stage 3 reasons, Stage 4
source refs/categories, Stage 4.5 proposal/validation, Stage 5 would-remove IDs,
Stage 6 records/counts, and final overview. No key or environment contents are
printed. Three small offline safety checks cover path isolation, restoration
of production settings and mocked full-flow execution:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.memory.test_memory_debug -v
```

### Context routing

Routing chooses *which data to include*; the router does not answer the user or
change the calendar. The final selection has this shape:

```json
{
  "activities_scope": "today",
  "include_exams": true,
  "exam_scope": "upcoming"
}
```

| Stage | Current behavior |
| --- | --- |
| 1 | Local keyword/phrase router. A confident, valid match is used immediately. Conflicting time scopes, source exclusions, and joke/explanation/general-advice phrases can defer to semantic routing. |
| 2 | Small OpenAI classifier when Stage 1 is not confident. It independently selects intent and required observations, returning a validated activity time scope, separate exam scope, activity/exam flags, optional memory selection and confidence. It receives the request and at most two brief recent turns, not the activity/exam observations. |
| 3 | Fallback OpenAI classifier when Stage 2 is unavailable, invalid, or low-confidence. It receives limited request/history and earlier routing metadata, not the full observations. |

If the later classifiers cannot produce a usable selection, the existing safe
default is today's activities plus upcoming exams, with explicitly excluded
sources removed. Stage 1 remains the initial
no-LLM route. The classifiers select context only; the main study agent generates
the user-facing response afterward.

#### Stage 2: intent and information dependencies

The intent describes what the user wants; observation flags describe the facts
needed to answer. `general_question` can therefore request tomorrow's activities
for a personal alarm, wake-up or departure recommendation. A joke or explanation
about alarm clocks needs no schedule data. Explicit exclusions override inferred
usefulness: general wake-up advice without calendar access selects no activities.
Missing commute/preparation information is left for the main agent to clarify.

Stage 2 uses a strict response contract, now with an independent `exam_scope`:

```json
{
  "intent": "general_question",
  "time_scope": "tomorrow",
  "include_activities": true,
  "include_exams": false,
  "exam_scope": null,
  "memory": null,
  "confidence": "high"
}
```

The converted context is also validated before Stage 2 is accepted. Invalid,
unavailable or low-confidence results reach the existing Stage 3 fallback.
Current observations remain authoritative for live schedules; historical
questions can separately select existing memory sources. No new source flags,
memory storage, observation builders or action behavior are introduced here.

#### Independent study windows and exam horizons

`time_scope` controls the activity window. `exam_scope` controls which exams are
relevant independently of that window or the intent label. For example:

```json
{
  "intent": "study_planning",
  "time_scope": "tomorrow",
  "include_activities": true,
  "include_exams": true,
  "exam_scope": "upcoming",
  "memory": null,
  "confidence": "high"
}
```

This sends tomorrow's commitments alongside upcoming exams over the existing
30-day horizon, so an exam later in the week is not hidden. Explicit exam
listings still use their requested scope: "exams tomorrow" selects `tomorrow`.
"Plan study tonight for exams this week" can use activity scope `today` and
exam scope `this_week`. Stage 3 supports the same independent scope field.

Allowed exam scopes are `today`, `tomorrow`, `week`, `this_week`, `next_week`,
`month`, and `upcoming`. When exams are excluded, `exam_scope` must be null.
For compatibility, old results without this field default to `upcoming` for
study planning; other dated requests use their date scope. Inclusion flags
remain independent of intent, and invalid scope combinations reach fallback.

#### Explicit source exclusions

`ai/context/policy.py` recognizes direct phrases such as "don't use my calendar",
"do not consult my schedule", "without my timetable", and "don't show exams".
Calendar/schedule/timetable exclusion blocks both activities and exams, since
both can appear in the calendar. Excluding exams alone still permits activities.
The guard requires a direct source exclusion; "I'm not sure about my exams",
"don't delete my activities", "don't ignore my exams", and "without forgetting
my exams" do not revoke read access. "Without using my calendar" does.

The guard is conservative phrase matching, not a complete natural-language
negation parser; Stage 2 still interprets the full message. Recognized exclusions
are enforced after every routing stage, including safe fallback, again before
observation collection, and before recovery. The main agent receives a separate
`excluded_sources` list, and the context inspector response includes that list.
An excluded source may remain `not_selected` in the status manifest, but that is
not permission to recover it: backend policy rejects the request before reading.

#### Offline context-correctness regressions

The regression suite checks exclusions even with faulty model flags, independent
study/exam periods, future windows without today's current/next data, NULL times,
and fresh observations kept separate from older conversation claims. Integration
fixtures use the existing insert/calendar functions with an in-memory SQLite
database switched to read-only before observation reads. No project database,
secrets, or live model calls are needed.

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_context_policy backend.tests.ai.test_routing_review backend.tests.ai.test_activity_observation_scopes backend.tests.ai.test_context_selection_regressions backend.tests.ai.test_context_recovery backend.tests.ai.test_stage_two_check -v
```

These tests verify backend correctness and what is transmitted, not whether a
real model will reason correctly. Actual semantic evaluation remains opt-in.

#### Direct Stage 2 regression checks

The exact alarm/tomorrow question currently matches Stage 1 confidently, so an
answer in the app may not exercise Stage 2. Inspect the reported routing stage
for full-app tests. The following developer command bypasses Stage 1 and Stage 3
and calls only the Stage 2 classifier when explicitly enabled.

| Case | Request | Activities | Exams | Memory |
| --- | --- | --- | --- | --- |
| A | What time should I set my alarm tomorrow? | Tomorrow | None | None |
| B | What time should I wake up tomorrow? | Tomorrow | None | None |
| C | When should I leave home tomorrow? | Tomorrow | None | None |
| D | What should I study tonight? | Today | Upcoming | None |
| E | What exams do I have this week? | None | `this_week` | None |
| F | Tell me a joke about alarm clocks. | None | None | None |
| G | How does an alarm clock work? | None | None | None |
| H | Don't use my calendar. Give general wake-up tips. | None | None | None |
| I | Don't show exams; tell me my schedule tomorrow. | Tomorrow | None | None |
| J | What did we decide last month about my study plan? | None | None | Global, last month |
| K | Help me plan study tomorrow for upcoming exams. | Tomorrow | Upcoming | None |
| L | Don't use my calendar; give generic wake-up advice for tomorrow. | None | None | None |
| M | What exams do I have today? | None | Today | None |
| N | Help me plan study tonight for exams this week. | Today | `this_week` | None |
| O | Tell me a joke about alarm clocks tomorrow. | None | None | None |
| P | What should I study next week for upcoming exams? | `next_week` | Upcoming | None |

From the project root, preview the cases and expectations for free:

```bash
backend/.venv/bin/python -B -m backend.app.dev.stage_two_check
```

This default mode makes no model calls and does not verify semantic accuracy.
To test one case with the actual classifier, explicitly enable **paid API usage**:

```bash
backend/.venv/bin/python -B -m backend.app.dev.stage_two_check --case A --llm
```

Repeat `--case` to select several cases, or omit it to evaluate all sixteen:

```bash
backend/.venv/bin/python -B -m backend.app.dev.stage_two_check --llm
```

To evaluate only the newly fixed horizon/exclusion cases, this explicitly makes
four paid classifier calls:

```bash
backend/.venv/bin/python -B -m backend.app.dev.stage_two_check --case K --case L --case M --case N --llm
```

Live mode reads the API key using the existing backend configuration and uses
the same Stage 2 model as the app. It makes one classifier request per selected
case with retries disabled. It prints the classification, selected scopes and
pass/fail result, never the key. A low-confidence result is marked unsuccessful
for these clear cases; the command does not call Stage 3. It does not open SQLite,
retrieve conversations/memory, run observations or call the main planning agent.
Matching is based on required context rather than insisting on a particular
intent label. Case J checks global scope and the symbolic `last_month` reference;
the validated memory sources and search terms are shown for manual inspection.
The evaluator intentionally does not apply backend exclusion masks: incorrect
classifier flags must fail the semantic check rather than be hidden by a guard.

Offline tests verify validation, observation selection, fallback and evaluator
isolation using mocked model responses. They do not prove the prompt's semantic
accuracy. Run them without an OpenAI charge:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_ai_proposal backend.tests.ai.test_observation_collection backend.tests.ai.test_routing_review backend.tests.ai.test_stage_two_check -v
```

### Activity and exam observations

The activity observation builder uses existing calendar recurrence logic to
resolve occurrences. Its scopes are:

| Scope | Data sent |
| --- | --- |
| `today` | Current activity or activities, next activity, and relevant activities today. |
| `tomorrow` | Tomorrow's activity occurrences. |
| `week` | Today's information plus up to 20 occurrences across today and the following six dates. |
| `this_week` | Remaining occurrences in the current Monday–Sunday week. |
| `next_week` | Occurrences in the next Monday–Sunday week. |
| `month` | Occurrences from today through the end of the current month. |
| `all` | Activity definitions and the full count, with bounded descriptive detail. |

Windows that do not contain today, such as `tomorrow` and `next_week`, omit
`current`, `current_count`, `next`, `today`, and `today_count` entirely and do
not query today's current/next activities. Windows containing today retain
those fields. Every dated occurrence and busy interval belongs to the returned
period; date-only items retain null times and still count as relevant data.

Detail lists use a 20-item/6,000-character budget. Date-window observations
include `period`, `count`, `truncated`, complete merged `busy` time intervals,
and `untimed_count`. Missing detailed cards do not imply free time. Untimed
activities remain represented in counts and cannot establish availability.

The exam observation builder keeps exams separate from activities. By default,
it includes exams from today through the next 30 days, limits the detailed list
to 20, and calculates `days_left` in Python. The router can narrow exam dates
for today, tomorrow, rolling/calendar week, or month requests. Exam responses
also report period, total count and truncation. Missing start/end times remain `null`; no
time is invented. Neither builder sends the entire database by default, and
neither produces an explicit list of free time slots.

The main request contains a `request` field, a backend-generated `clock`
(`as_of`, date, time and `Pacific/Auckland` timezone), and a separate `observations` object
with only the selected `activities` and/or `exams` sections. Recent conversation
turns are supplied as separate messages, not mixed into the observation data.
The current database observations take precedence over outdated statements in
the conversation.

Mixed historical/current requests retain fresh observations; for example,
“Last time we discussed my exam. What is its current date?” selects exam facts
as well as historical context. “What did I just say?” alone stays a recent-chat
question, while adding “what exams do I have today?” also selects today's exams.

### Main agent output

The study agent returns a validated proposal with a user-facing `message` and
an `actions` list:

```json
{
  "message": "You could study after your lecture.",
  "memory_request": null,
  "missing_context": [],
  "actions": [
    {
      "tool": "add_activity",
      "arguments": {
        "name": "Revision",
        "category": "Study",
        "subject": "COMPSCI 130",
        "activity_type": "one_time",
        "date": "2026-09-30",
        "weekday": null,
        "start_time": "18:00",
        "end_time": "19:00"
      }
    }
  ]
}
```

The example is a proposal shape, **not** a record of an activity that was
created. A response with `"actions": []` is also valid. Validation rejects
unknown tools and malformed activity arguments. `add_activity` is the only
supported proposed tool; the agent cannot issue SQL. The model and reasoning
effort for the main agent are configurable separately from the routing stages.

### One-shot context recovery

Each main-agent input now includes a small `context_status` manifest, separate
from the observation data:

```json
{
  "context_status": {
    "current_chat": "provided",
    "activities": "not_selected",
    "exams": "not_selected",
    "global_memory": "not_selected"
  },
  "context_recovery_remaining": 1
}
```

`provided` means data is included; `empty` means the source was queried with no
relevant records; `not_selected` means it was not fetched; `unavailable` means it
cannot be supplied. The current request and bounded recent turns already form
the supplied current-chat context. Global memory keeps its existing scoped
retrieval; it is unavailable without a trusted conversation/session identifier.
No unselected observations are sent alongside this manifest. Full observation
counts distinguish genuinely empty results from truncated or untimed data.

If essential activity/exam data was omitted, the main agent may return a control
response instead of asking the user for schedule information the app can read:

```json
{
  "message": null,
  "actions": [],
  "memory_request": null,
  "missing_context": [
    {"source": "activities", "time_scope": "tomorrow"}
  ]
}
```

`MissingContextRequest` in `ai/agent/contracts.py` permits only `activities` and
`exams`, with at most two distinct requests. Activity scopes are `today`,
`tomorrow`, `week`, `this_week`, `next_week`, `month`, `all`; exam scopes use the
same date scopes plus `upcoming`, without `all`. Python also requires each
requested source to currently be `not_selected`. Unknown sources, extra fields,
unsupported scopes, repeated sources and actions attached to a recovery request
are rejected. Provided, empty and unavailable sources are never re-fetched by
this fallback. Recognized explicit user exclusions are separately enforced by
backend policy, not just the agent instructions. An excluded source cannot be
recovered even if its manifest status is `not_selected`.

`ai/agent/context_recovery.py` defines `MAX_CONTEXT_RECOVERY_RETRIES = 1`.
`ai/agent/service.py` uses the existing observation collector/builders to fetch
only the requested sources, merges them without replacing other observations,
updates the manifest, and makes at most one follow-up main-agent call. Failed
activity/exam reads become `unavailable`; a failed recovery with no usable reads
returns a clarification without another model call. A successful empty query
is sent to the one retry as `empty`.

The existing `memory_request` lookup and new context recovery share this single
follow-up budget. They can be satisfied together before one retry, but neither
can trigger a third main-agent call. A repeated request after the retry returns
a safe clarification with no proposed actions. Intermediate control responses
are never saved as completed conversation turns. Normal action validation and
proposal-only behavior are retained; recovery never calls a mutation tool.

The existing **How the agent used context** inspector shows initial/final source
statuses, requested scopes, recovery attempts, and main-agent call count. It
does not display model reasoning or private request/error details.

To reproduce the alarm routing failure deterministically without a paid model
call or changes to your database, run from the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_context_recovery.ContextRecoveryTests.test_alarm_recovers_once -v
```

The test forces the router to omit activities, simulates the model's structured
request, checks that tomorrow's activity builder is called once, and verifies a
second/final main-agent response. The complete recovery suite also covers jokes,
empty/unavailable/provided observations, malformed requests, exhausted budgets,
memory interaction, and an actual activity builder using a read-only in-memory
database:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_context_recovery -v
```

In the running app, an ordinary alarm/tomorrow request may already be handled
correctly by Stage 1 and show zero recovery attempts. That is the intended cheap
path. Inspect the context panel if a real routing omission triggers recovery;
one recovery can cost one additional main-agent request. These offline tests
verify orchestration and validation, not the live model's detection accuracy.

## Not implemented yet

The React AI Agent now sends conversation messages through FastAPI and displays
saved replies, proposals and context inspectors. AI Settings configures the key
locally without returning it to React. There is still no Accept/Reject UI, no
approval/execution endpoint, and no automatic call to `add_activity` for an
AI-proposed action. A normal activity can still be added through the existing
manual app workflow.

Automatic archive-compaction runs, automatic durable-memory extraction, Screen
Time context routing, goals and study-history
observations, and observation hash/change caching are not part of the normal
AI request flow. They should not be assumed to affect a current AI response.

The intended later workflow is: show a validated proposal to the user, ask for
approval, then use a separate backend action to save an approved activity and
refresh the calendar. That approval and execution flow has not been built.

## Test without an OpenAI charge

From the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_ai_proposal -v
```

These tests use mock model responses and temporary test data. They check
routing, observation selection, recent-turn limits, structured validation and
the proposal endpoint without making a live OpenAI request or inserting a
proposed activity into the project database.

To run the full backend regression suite, including Stage 6:

```bash
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -p 'test_*.py'
```
