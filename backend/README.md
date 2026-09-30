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

Automatic archived-conversation retrieval or summarization, Screen Time context routing,
goals and study-history observations, and observation hash/change caching are
also not part of this workflow. They should not be assumed to affect a current
AI response.

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
