# Agent Context Inspector

The AI Agent page sends requests to the existing `POST /ai/propose` endpoint
(through Vite's `/api` proxy). Expand **How the agent used context** below the
response. The panel starts collapsed and has no action-execution controls.

## Response schema

The existing `message`, `actions` and `memory_request` fields are unchanged.
The HTTP response adds the following object. This is schema notation, not JSON:

```text
agent_context: {
  routing: {
    stage: "stage_1" | "stage_2" | "stage_3" | "safe_fallback",
    label: string,
    status: "matched" | "fallback",
    intent: string | null,
    time_scope: string | null,
    reason: string
  },
  context_sources: [{
    source: "activities" | "exams" | "recent_memory" |
            "raw_archive" | "compressed_archive" | "durable",
    label: string,
    selected: boolean,
    authority: "current" | "historical" | "historical_summary",
    reason: string
  }],
  retrieved_memory: [{
    source_type: "raw_archive" | "compressed_archive" | "durable",
    label: string,
    authority: "historical" | "historical_summary",
    category: string | null,
    excerpt: string | null,
    source_id: string | null,
    timestamp: string | null,
    period_start: string | null,
    period_end: string | null,
    source_refs: string[],
    time_match: string | null,
    used_in_model: boolean,
    reason: string
  }],
  memory_lookups: [{
    phase: "initial" | "followup",
    sources: string[],
    status: "ok" | "empty" | "partial" | "unavailable",
    result_count: integer,
    truncated: boolean,
    unavailable_sources: string[],
    used_in_model: boolean
  }],
  memory_message: string,
  authority_note: string
}
```

Stage 1 does not classify intent, so its intent is null rather than an invented
label. Stage 2/3 intent and time scope are copied from their existing validated
decisions. Stage 1 time scope comes from the selected activity/exam/memory scope.
Routing reasons are fixed factual backend descriptions, not model reasoning.

Activities/exams are labelled `current`; compressed memory is
`historical_summary`; other memory is `historical`. Current observations remain
the source of truth. Selected memory means a lookup was requested, not that it
found a match. Lookup status and `used_in_model` distinguish empty/unavailable
results and follow-up searches that did not lead to another model call.

Excerpts are capped at 240 characters plus an ellipsis, API keys are redacted,
and provenance references are limited to five per item. Existing retrieval
limits and session isolation remain unchanged. IDs, timestamps and periods are
under a nested provenance disclosure. Missing categories/timestamps are not
invented. Proposed actions are displayed as their existing tool/argument fields.

No system prompts, hidden reasoning, raw model responses or API credentials are
included. The metadata is stripped before saving the completed conversation
turn, so it is not archived or fed back to the model as conversation history.

## Manual tests A–F

Start the existing backend and frontend, configure the API key through the
existing settings, and open **AI Agent** from the menu. These live requests can
incur OpenAI charges. For each request, click **Ask AI**, wait for the response,
then expand **How the agent used context**.

| Case | Request/setup | Check |
| --- | --- | --- |
| A | `What am I doing today?` | Stage 1; activities selected; historical lookup normally not requested. Recent memory may be selected if prior turns exist. |
| B | `I've got something important coming up and I'm free later. What should I focus on?` | Actual stage shown, potentially Stage 2; activities/exams reflect the validated classification. |
| C | In the same browser session as an existing archived COMPSCI discussion from last week, ask `What did we decide last week about COMPSCI revision?` | Memory selected; matching excerpts and provenance shown. Without qualifying history, an empty result is correct. Do not expect another browser session's memory. |
| D | Run the controlled offline test below. | It forces Stage 1 unresolved and Stage 2 unavailable, then verifies a valid Stage 3 result reports `stage_3`. No natural phrase guarantees Stage 3; do not change production routing just to force it. |
| E | `Propose a one-time COMPSCI revision activity tomorrow from 18:00 to 19:00; do not save it.` | If the model proposes an action, its fields appear under Proposed Actions. There is no execution/approval button and no new calendar row. The model can validly decline and return no actions. |
| F | `What did we discuss before about nonexistent-topic-938472?` | No matching historical memory (assuming that topic is absent); no fabricated excerpts. Unavailable storage is shown separately from no match. |

Free deterministic verification from the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_agent_transparency -v
```

This covers all routing stages, unchanged model inputs, authority/provenance,
redaction, bounded excerpts, no-match/unavailable states, failed follow-up
lookups, and exclusion of metadata from saved conversation turns.
