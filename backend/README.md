# Study Planning App

This README explains how to run the project and describes the backend as it
currently works. The AI agent can **propose** an activity, but cannot yet save
an AI-proposed activity.

## Run the API

From the project root, install dependencies into the existing backend virtual
environment and start FastAPI:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m uvicorn backend.fastapi_test:app --reload --port 8001
```

Open `http://127.0.0.1:8001/docs` for the API documentation. Press `Ctrl+C` in
the terminal to stop the server. The FastAPI `app` is in
`backend/fastapi_test.py`; `backend/app/main.py` is an interactive Python program,
not the ASGI app. The frontend's Vite `/api` proxy targets port 8001.

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

## AI study-planning workflow: implemented

```text
POST /ai/propose with a user message and browser session
  -> read up to the configured number of recent completed turns (5–100)
  -> choose activity/exam context with the Stage 1/2/3 routing pipeline
  -> build fresh observations from the current SQLite data
  -> send the request, selected observations and recent turns to OpenAI
  -> validate a structured message and proposed actions
  -> return the proposal; do not execute its actions
```

The API checks for a configured `OPENAI_API_KEY` before calling OpenAI. The key
stays in the backend's local environment configuration; it is not returned in
the proposal. `/ai/propose` reads the database without writing to it.

### Recent conversation memory

A completed turn contains a user message and the assistant's response. The
backend keeps 5–100 recent completed turns per browser session in memory; the
default is 5. Change the limit in AI Settings. When a new turn exceeds the
limit, the oldest turn is appended to the Git-ignored
`backend/ai_memory_archive.jsonl` file. Lowering the limit archives excess
in-memory turns before the next AI request; increasing it does not restore
turns already archived. Archive entries preserve their order and session ID.

Only recent turns are supplied to normal model requests. An archive-search helper
exists, but it is not automatically called or sent to the model. Recent in-memory
turns do not survive a server restart; the archive is not automatically restored.
Failed proposals do not become completed turns. The conversation records a
proposal as a proposal, not as a completed calendar change.

### Archive compaction threshold (Stage 1)

`backend/app/ai_memory.py` defines `ARCHIVE_TURN_THRESHOLD = 100` and
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
backend/.venv/bin/python -B -m unittest backend.test_ai_archive_compaction -v
```

The tests cover archives of 0, 50, 99, 100, 101, and 150 turns.

### Archive candidate selection (Stage 2)

`select_archive_compaction_candidates()` uses the Stage 1 threshold. If the
archive exceeds 100 turns, it returns up to 50 oldest archived turns as
`compaction_candidates`, along with candidate/remaining counts and known
timestamp bounds. Dated turns are ordered by their stored completion times;
undated legacy turns use archive file order after dated turns. At 100 archived
turns it selects none; at 101 it selects 50 and leaves 51 unselected. This
function reads only archived turns, not recent in-memory turns. It does not
rewrite the archive.

### Archive candidate protection labels (Stage 2.5)

`backend/app/ai_archive_protection.py` classifies only the Stage 2 candidate
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
backend/.venv/bin/python -B -m unittest backend.test_ai_archive_compaction backend.test_ai_archive_protection -v
```

### Resolve uncertain archive candidates (Stage 3)

`backend/app/ai_archive_llm_classifier.py` sends only Stage 2.5 `uncertain`
turns to a small OpenAI classification call. Its structured result must label
each candidate `protected` or `compactable` with a compatible category. A
missing key, failed call, or invalid response keeps the affected batch
`protected` rather than risking its removal. This stage does not edit the
archive. Its tests mock OpenAI:

```bash
backend/.venv/bin/python -B -m unittest backend.test_ai_archive_llm_classifier -v
```

### Summarize compactable turns (Stage 4)

`backend/app/ai_archive_summary.py` summarizes only candidates with final
`compactable` status. It produces short bullets and keywords under the fixed
categories `activities`, `exams_tests`, `study_topics`, `technical_issues`, and
`general`, plus the source-turn refs and time range. It can flag meaningful
`general` bullets for a category review. Protected candidates are excluded.
The result is still in memory; no raw archive turns are removed.

### Review a possible new category (Stage 4.5)

`backend/app/ai_archive_category_review.py` runs a second, small model call
only when Stage 4 flags unresolved `general` items. The model may propose at
most one broad new category. Python checks the name, duplicates/synonyms,
protected-memory categories, and evidence from at least two matching summary
items. If accepted, only those summary bullets move to the new category in
the in-memory result. Rejected bullets stay under `general`; no archive file
is changed at this stage. These tests also mock OpenAI:

```bash
backend/.venv/bin/python -B -m unittest backend.test_ai_archive_summary backend.test_ai_archive_category_review -v
```

### Persist a compacted summary (Stage 5)

`backend/app/ai_archive_persistence.py` exposes
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
backend/.venv/bin/python -B -m unittest backend.test_ai_archive_persistence -v
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
| 1 | Local keyword/phrase router. A confident, valid match is used immediately. It also recognizes ambiguity such as conflicting time scopes or negated exam requests. |
| 2 | Small OpenAI intent-classification call when Stage 1 is not confident. It returns a validated intent, time scope, activity/exam flags and confidence. It receives the request and at most two brief recent turns, not the activity/exam observations. |
| 3 | Fallback OpenAI classifier when Stage 2 is unavailable, invalid, or low-confidence. It receives limited request/history and earlier routing metadata, not the full observations. |

If the later classifiers cannot produce a usable selection, the existing safe
default is today's activities plus upcoming exams. Stage 1 remains the initial
no-LLM route. The classifiers select context only; the main study agent generates
the user-facing response afterward.

### Activity and exam observations

The activity observation builder uses existing calendar recurrence logic to
resolve occurrences. Its scopes are:

| Scope | Data sent |
| --- | --- |
| `today` | Current activity or activities, next activity, and relevant activities today. |
| `week` | Today's information plus up to 20 occurrences across today and the following six dates. |
| `month` | Today's information plus occurrences from today through the end of the current month. This scope currently has no 20-item cap. |
| `all` | A broader set of activity definitions and a count; this can be much larger than the other scopes. |

The exam observation builder keeps exams separate from activities. By default,
it includes exams from today through the next 30 days, limits the detailed list
to 20, and calculates `days_left` in Python. The router can narrow exam dates
for today, week, or month requests. Missing start/end times remain `null`; no
time is invented. Neither builder sends the entire database by default, and
neither produces an explicit list of free time slots.

The main request contains a `request` field and a separate `observations` object
with only the selected `activities` and/or `exams` sections. Recent conversation
turns are supplied as separate messages, not mixed into the observation data.
The current database observations take precedence over outdated statements in
the conversation.

### Main agent output

The study agent returns a validated proposal with a user-facing `message` and
an `actions` list:

```json
{
  "message": "You could study after your lecture.",
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

## Not implemented yet

The React AI Agent page has an Ask AI placeholder, but it does not call
`/ai/propose` or display returned proposals. The AI Settings key form is also a
frontend placeholder, although backend key-configuration endpoints exist; the
model selector is connected to the backend. There is no Accept/Reject UI, no
approval/execution endpoint, and no automatic call to `add_activity` for an
AI-proposed action. A normal activity can still be added through the existing
manual app workflow.

Automatic archive-compaction runs and automatic retrieval of archived turns or
compressed summaries, Screen Time context routing, goals and study-history
observations, and observation hash/change caching are not part of the normal
AI request flow. They should not be assumed to affect a current AI response.

The intended later workflow is: show a validated proposal to the user, ask for
approval, then use a separate backend action to save an approved activity and
refresh the calendar. That approval and execution flow has not been built.

## Test without an OpenAI charge

From the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.test_ai_proposal -v
```

These tests use mock model responses and temporary test data. They check
routing, observation selection, recent-turn limits, structured validation and
the proposal endpoint without making a live OpenAI request or inserting a
proposed activity into the project database.
