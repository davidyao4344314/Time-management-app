# Stage 8: Action Layer, native tool proposals and user confirmation

This stage establishes contracts and trusted backend boundaries. Commit 8.2 adds
an explicitly opted-in real `add_activity` tool using the existing service. The normal
AI request never executes a planner tool. Commit 8.3 adds the generic approval
UI/API. Commit 8.4 connects native LLM function requests to pending proposals
in that same UI; only a separate explicit user confirmation saves an activity.
The tools now also support `delete_activity` with the same separate confirmation
boundary. `edit_activity` now uses it too, with a database-backed old → new review
and an atomic in-place update. Exam tools and bulk changes are not enabled.

## Structure and responsibility

```text
backend/app/ai/actions/
├── __init__.py       # Package description; no initialization side effects
├── contracts.py      # Add/delete/edit activity schemas + routes, proposals/results/statuses
├── tools.py          # Tool public contract, strict input validation, optional trusted handler
├── registry.py       # Explicit tool registration/discovery; proposal-only default registry
├── routing.py        # Existing agent output -> validated pending proposals or reserved route
├── approval.py       # Backend-held temporary lifecycle; explicit approve/reject decisions
├── execution.py      # Approved ID -> trusted tool -> ActionResult
├── activity_tool.py  # Activity adapters and read-only change previews -> Activity service
├── service.py        # Owner-scoped presentation and decisions; temporary state
└── planning.py       # ResponsePlanner interface only; no implementation or model call
```

Three routes exist: `none`, `tool_action`, and `response_plan`. The latter is a
reserved backend-selected branch, not a new model-output field. It cannot be
combined with tool actions, and does not call a planner.

```text
validated agent result
        -> route_agent_output
             -> none: normal response
             -> response_plan: interface reserved for later
             -> tool_action: pending ActionProposal(s)
                                  -> explicit user decision
                                       -> reject: no execution
                                       -> approve: ActionExecutor.execute(proposal_id)
                                            -> trusted registry handler -> ActionResult
```

The router accepts the current validated `{message, actions, memory_request,
missing_context, ...}` response. It validates *all* action requests before
registering any proposals, generates backend UUIDs and generic display fields,
and never executes tools. Extra action fields such as `status`, `id` or
`requires_approval` are rejected. Tool selection is registry-driven, not an
add/edit/delete conditional chain.

The internal message/actions contract remains unchanged. Commit 8.4 changes
how the provider supplies actions: native function calls, not a text actions list.
The chat service reuses `prepare_tool_proposals()` from this router before
registering fresh completed requests with the existing owner-scoped service.

## Commit 8.2: approved activity creation

`AddActivityTool(connection)` is a trusted `Tool` adapter. The caller owns the
SQLite connection and explicitly opts in using `create_activity_tool_registry(connection)`.
It originally registered only `add_activity`; it now also registers
`DeleteActivityTool` and `EditActivityTool`, described below. The default
`create_proposal_tool_registry()` remains non-executable. Constructing either
registry creates no database rows and opens no connection.

The public input remains `AddActivityArguments`: `name`, `category`, `subject`,
`activity_type`, `date`, `weekday`, `start_time`, `end_time`. All keys are required;
unused/optional values are null. It does not expose source/external IDs, active
date ranges, SQL, paths or persistence objects. Commit 8.4 exposes this public
schema to the LLM; the executable handler is never exposed.

```text
backend-held approved proposal ID
    -> ActionExecutor
    -> ToolRegistry resolves AddActivityTool
    -> existing AddActivityArguments validates the contract
    -> activity_service.prepare_new_activity validates/prepares domain fields
    -> activity_service.create_activity_record
    -> existing add_activity + get_activity_by_id
    -> ActionResult(success=true, result={"activity_id": new_id})
```

Contract validation rejects missing/extra fields, invalid recurrence/date/time
values, and an end time not later than a start time. The existing service remains
responsible for domain preparation and validation; the adapter contains no SQL
or copied business rules. Creation uses the existing commit behavior and schema
defaults (`source="Manual"`, `external_id=NULL`). Date-only activities retain null times.

Tests register a pending proposal, explicitly approve it through `ApprovalBoundary`,
then execute only its ID. Supplying an object with `status="approved"` is not an
approval mechanism. Pending/rejected proposals never reach the service; completed
or failed proposals cannot execute again within the same boundary.

Commit 8.2 establishes this deterministic backend path. Commit 8.3 adds manual
confirmation below, and Commit 8.4 connects chat requests to pending review.
There are still no exam/bulk-change tools or durable approval storage.
Handler/service failures use the existing sanitized unconfirmed-outcome behavior;
a failed post-insert read must not be reported as proof that no row was created.

## Commit 8.3: generic Confirm / Cancel flow

The AI Agent page has a **Proposed changes** panel. `ActionProposalCard` displays
the backend's title, description and status without inspecting tool names. It
never calls the activity API to create data. Commit 8.4 now supplies pending
proposals from validated native calls as well as the optional development sample.

`ActionProposalService` owns one process-local `ApprovalBoundary`, owner links and
result receipts. It reuses the existing signed browser-profile identity; no owner
ID is accepted in request bodies. Proposals belong to that profile, not a chat.
Unknown and foreign IDs both return 404. Public views contain only:

```json
{
  "id": "backend-generated-uuid",
  "display_title": "Add Activity",
  "display_description": "The exact proposed change",
  "status": "pending_approval",
  "requires_approval": true,
  "result": null
}
```

The backend keeps tool arguments private and immutable behind the boundary.
The `result` field becomes the existing `ActionResult` after execution, not a
second result schema. Responses are not cached by the browser.

| Endpoint | Behavior |
| --- | --- |
| `GET /actions/proposals` | List the verified owner's display views and `dev_enabled` |
| `GET /actions/proposals/{id}` | Read one owned proposal/status/result |
| `POST /actions/proposals/{id}/decision` | Accept only `{"decision":"confirm"}` or `{"decision":"cancel"}` |
| `POST /actions/dev/proposals` | Accept only `{}`; create a pending sample if `ACTION_LAYER_DEV_MODE=1` |

Confirm verifies owner and pending status, opens the existing database connection,
approves through `ApprovalBoundary`, then invokes `ActionExecutor` with the trusted
activity registry. Cancel marks it rejected without opening an activity connection.
Extra body fields (arguments, tool name, approved status, owner, etc.) are rejected.
The service serializes decisions; repeat or concurrent confirmations return 409
instead of inserting again. Completed/failed result receipts remain available on
refresh during this process lifetime. Connection-open failure leaves the proposal pending.

The UI disables both controls during a decision and never retries automatically.
If a network/API error makes the outcome uncertain, refresh authoritative status
before making another decision. Handler failures retain the existing warning
that state might have changed; a failure does not promise rollback. A trusted
read-only preflight refusal reports that the action did not run and shows its
sanitized domain error on the card.

### Manual testing without an LLM

Stop the existing backend before restarting it from the project root:

```bash
ACTION_LAYER_DEV_MODE=1 backend/.venv/bin/python -m uvicorn backend.app.server:app --reload --port 8001
```

Run the frontend normally (`cd frontend`, then `npm run dev`). Open **AI Agent**:

1. Under Proposed changes, click **Create test proposal**. No activity is saved.
2. Click **Cancel**; status becomes rejected and nothing is created.
3. Create another test proposal and click **Confirm**. One real test activity named
   `Study Maths (approval test)` is saved; the card shows the executor result.
4. Refresh proposals/the page. The completed card must not offer Confirm again.
5. Open Activities/Calendar to verify the saved test activity on today's date at
   19:00–20:00. Remove it through the existing activity controls when finished.
6. A separate browser profile must not see/confirm the first profile's proposals.

This test uses your actual local database **only when you Confirm**. It makes no
OpenAI request. Automated tests instead use disposable databases and identities.
Start the backend without `ACTION_LAYER_DEV_MODE=1` to hide/disable the sample source.
Restart/reload discards pending proposals and receipts; saved activities remain.
Use a single backend process for this local stage. This is not durable workflow
storage, multi-worker coordination or a restart-safe exactly-once guarantee.

## Commit 8.4: native model requests become pending proposals

```text
existing observations + recent chat + user request
    -> existing Responses request + schema-only add/delete/edit activity definitions
    -> native function_call (or ordinary structured advice)
    -> agent/tool_calls.py: normalize and validate against ToolRegistry
    -> existing internal {message, actions, memory_request, missing_context}
    -> conversations/service.py: prepare pending proposals, save completed chat
    -> API-injected registration in the SAME ActionProposalService
    -> Proposed changes panel -> explicit Confirm / Cancel
```

`public_agent_tools()` derives all three function definitions from the existing
schema-only registry: name, description, strict input schema, no handler or
approval authority. `tool_choice="auto"` allows ordinary answers;
`parallel_tool_calls=False` limits the request to zero/one call. The adapter
reads Responses `function_call` items (`name`, JSON `arguments`, `call_id`,
completed status), not free-form text. This follows the
[OpenAI function-calling format](https://developers.openai.com/api/docs/guides/function-calling).

Registry lookup and strict activity-tool argument validation reject unknown
tools, missing/extra fields, invalid recurrence/date/time values and forged
approval/metadata fields. SDK JSON parsing errors become sanitized response
errors. Tool calls cannot coexist with unresolved context/memory requests.
Incomplete/invalid replies fail the chat request (502), creating no proposal
or activity. Text `actions` must be empty; a fake tool call in text is not executed.

**Mixed response policy:** retain a valid structured user-facing message and
display the native request separately for review. A tool-only reply gets a small
backend message explaining that nothing is saved until confirmation. No second
model call is made to acknowledge execution. The internal actions list is retained
for existing inspectors/history as proposal evidence, never proof of execution.

`api/action_runtime.py` is the single composition root shared by the chat and
approval adapters. The chat service receives a registration callback; it invokes
no executor or tool handler and imports no HTTP layer. It prepares all requests before
saving chat and registers only newly completed requests. Replaying a request ID,
refreshing chat, or reading old replies never creates another proposal. The UI
refreshes proposals when a new assistant reply appears. It queues a read rather
than aborting/retrying an in-flight confirmation.

Proposals remain process-local. A restart (or interruption after chat persistence
but before registration) can lose pending review state; old saved chat is **not**
rehydrated into executable authority. Ask again to create a fresh proposal and
check the calendar first if an earlier execution outcome was uncertain. Nothing
automatically approves, retries or executes during generation or recovery.
The compatibility `/ai/propose` preview path returns the internal proposal only;
the current `/conversations/{id}/messages` chat path registers reviewable proposals.

### Test the model-connected flow

No-charge tests from the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_llm_action_proposals -v
```

They cover schema exposure, real SDK function-call parsing, ordinary/mixed/tool-only
responses, invalid/unknown requests, pending/no-write behavior, owner isolation,
retry/restart safety, cancellation and exactly one saved activity after Confirm.
All model calls are mocked and all databases/identity keys are disposable.

Optional live test (uses your configured key and may incur charges):

1. Run backend/frontend normally; no development flag is needed.
2. In AI Agent, ask a normal question. It should not force an activity proposal.
3. Ask to add a named one-time study activity with a specific date/start/end.
4. Review the pending card. Check Activities: it must not exist yet.
5. Cancel one proposal. No row should be saved.
6. Request another and Confirm once. Check Activities/Calendar for one saved row.
7. Refresh/replay the chat request: no second proposal or saved copy is created.

Only `add_activity`, `delete_activity` and `edit_activity` are exposed. Additional tools, durable proposals, editing pending proposals,
post-execution model continuation, sequential execution loops and a date engine
remain deferred. Context routing, recurrence, imports and database schemas are unchanged.
Compact activity observations now include database `id` and `activity_type` for
exact deletion targeting, retaining existing detail limits and excluding import IDs.

## Approved deletion of one activity

The native tool accepts exactly:

```json
{"activity_id": 12, "expected_name": "COMPSCI revision"}
```

Both values must come from fresh activity observations. IDs must be positive
integers (not strings or booleans); names must be nonblank. Extra fields,
name-only deletion and lists of IDs are rejected. If current target details are
missing, use existing one-shot activity context recovery or ask which activity
the user means. Never select the first same-name record automatically.

Before registering the pending proposal, the chat service uses its read-only
observation connection to verify ID/name and build a review description from
the actual row: category, subject, recurrence, date/weekday, available times,
active dates and source. External IDs and UoA UID mappings are not displayed.
No row is deleted during generation or preview.

```text
delete_activity native request
    -> validated pending proposal + database-backed review card
    -> explicit Confirm through existing /actions/proposals/{id}/decision
    -> executor -> DeleteActivityTool read-only preflight
    -> activity_service.delete_activity_record
    -> transaction: recheck ID/name, existing delete_activity(commit=False)
    -> commit -> {"activity_id": 12, "deleted": true}
```

Cancel does not open execution resources. Confirm checks the target again; a
missing or renamed record fails without deleting another activity. The transaction
rechecks under SQLite's write lock and requires exactly one affected row. The
existing standalone `delete_activity` still commits by default. Different records
with the same name remain untouched. Existing foreign-key cascade removes only
the deleted activity's dependent UoA UID mappings.

Deletion is permanent in the app. Deleting a daily/weekly activity removes the
entire recurring row, not one occurrence; the card warns about this. Imported
rows are local copies: Canvas/UoA feeds are unchanged, and later imports may
restore them. No exam or delete-all tool is added; no schema/import logic changes.

Offline tests (temporary SQLite and mocked OpenAI; no charges):

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_delete_activity_tool backend.tests.ai.test_llm_action_proposals -v
```

For a live test, create a disposable manual activity and note its ID. Ask the AI
to delete that exact ID/name, then Cancel and verify it remains. Ask again,
review the card and Confirm once; open Activities/Calendar to verify removal.
Do not test on records you need to keep. A live AI request may incur charges;
confirmation itself makes no additional model request. Reload/restart loses
pending proposals/receipts as before and never recreates authority from old chat.

## Approved editing of one activity

Use the same native request → pending card → Confirm/Cancel flow. The model
can request one or several changes to a current activity:

```json
{
  "activity_id": 12,
  "expected_name": "COMPSCI revision",
  "changes": [
    {"column_name": "start_time", "new_value": "19:00"},
    {"column_name": "end_time", "new_value": "20:00"}
  ]
}
```

`EditActivityArguments` permits only the eight existing editable columns:
`name`, `category`, `subject`, `activity_type`, `date`, `weekday`, `start_time`,
`end_time`. Changes contain a string or null value, at most eight distinct
fields, and no extra keys. IDs, source, external IDs, active date ranges and
UID mappings cannot be edited. Native calls remain limited to one tool request
per reply; one edit request may contain several changes.

`activity_service.prepare_activity_update()` checks ID/name and merges only
the requested fields into the actual row. It reuses `prepare_new_activity()`
for final-state domain validation, including the combined start/end range.
One-time activities require a date; weekly activities require a weekday.
Changing recurrence clears unused date/weekday values; a requested non-null
value for an inapplicable field is rejected. Null can clear optional subject/time
values; no fake times are assigned. Invalid and no-op edits create no pending card.

Read-only preview shows the current activity and each actual old → new change,
including automatic null clearing. Recurring edits apply to the whole activity,
not one occurrence; imported edits affect only the local row. Cancel opens no
execution connection. Confirm rechecks ID/name and final values before writing.

`update_activity_fields()` owns one SQLite transaction, revalidates under its
write lock, then calls the existing `edit_activity(..., commit=False)` for each
changed field. It never deletes/recreates the activity or adds duplicate UPDATE
SQL. A failure rolls back the complete edit; executor failures remain sanitized.
The success receipt contains the activity ID, `updated: true`, and changed field
names, not source identifiers. Existing manual edit endpoints are unchanged.

No additional endpoint or frontend editing system is needed. The existing
`/actions/proposals/{id}/decision` and generic review card are reused. No schema,
Canvas/UoA import, recurrence or context-routing changes are made.

Offline tests:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_edit_activity_tool backend.tests.ai.test_llm_action_proposals -v
```

For a live test, create a disposable activity and note its ID/name. Ask:
“Change activity ID 12, COMPSCI revision, to 19:00–20:00.” Cancel first and verify
it remains unchanged; ask again and Confirm. Open Activities/Calendar to check
the updated times and unchanged ID. Test a recurrence change with an explicit
date/weekday, and test a disposable imported activity to confirm source and
external IDs remain unchanged. Live AI requests may incur charges; automated
tests use temporary databases and mocked OpenAI, never your real records.

## Proposal and result contracts

Example backend-created display snapshot:

```json
{
  "id": "backend-generated-uuid",
  "action_type": "tool_action",
  "tool_name": "add_activity",
  "arguments": {
    "name": "Maths revision",
    "category": "Study",
    "subject": "MATHS 102",
    "activity_type": "one_time",
    "date": "2026-10-09",
    "weekday": null,
    "start_time": "18:00",
    "end_time": "19:00"
  },
  "display_title": "Add Activity",
  "display_description": "Name: Maths revision\nCategory: Study\nSubject: MATHS 102\nActivity type: one_time\nDate: 2026-10-09\nStart time: 18:00\nEnd time: 19:00",
  "status": "pending_approval",
  "requires_approval": true
}
```

`ActionProposal` is a frozen Pydantic snapshot. Its nested arguments are copied
when stored/read: changing a returned snapshot cannot change trusted arguments
or authorize execution. `requires_approval` can only be `true`.

An `ActionResult` contains `proposal_id`, `success`, `result`, `error`, `message`.
`result` is a JSON-friendly dictionary or null; a failed result contains an error
and no success result. For example, the fake test tool returns:

```json
{
  "proposal_id": "backend-generated-uuid",
  "success": true,
  "result": {"echo": "Study"},
  "error": null,
  "message": "Fake Action completed."
}
```

## Approval and execution safety

```text
pending_approval -> rejected
pending_approval -> approved -> executing -> completed / failed
```

- Registration accepts pending proposals only. Approval requires an explicit
  `ApprovalDecision.APPROVE` or `REJECT`; creating/routing a proposal is not approval.
- The executor receives only a proposal ID and looks up authoritative state in
  the same `ApprovalBoundary`. Browser/model status fields never grant approval.
  Non-string, empty or whitespace-only IDs raise a controlled `ActionLayerError`
  before state lookup. A valid-looking but unknown ID returns a failure result.
- The boundary claims execution under a lock before invoking the handler. Pending,
  rejected, executing, completed and failed proposals cannot execute. Concurrent
  submissions cannot execute the same proposal twice within this boundary.
- Execution validates tool arguments again. Unknown tools, unavailable execution
  and invalid inputs are preflight refusals: this attempt did not run the action.
  If a handler raises after starting, or its returned result is not JSON-compatible,
  the outcome is reported as **unconfirmed**, not as proof that nothing changed.
  Check application state before proposing another attempt. `success: false` and
  terminal `failed` mean success was not confirmed; they do not promise rollback.
  The same proposal cannot be retried. Raw exception details are not exposed.
- `create_proposal_tool_registry()` reuses `AddActivityArguments` but registers
  **no executable handler**. Even an approved `add_activity` fails safely with
  `Execution is not available for this tool.` No exam/bulk-change tools exist;
  single-record delete/edit tools are available only through explicit approval.
- Approval state is temporary and instance-scoped, not persistent or global. A
  restart loses it. The generic HTTP adapter enforces signed profile ownership,
  never accepts client-supplied approved objects, and only executes through the
  existing boundary. Persistent proposals remain deferred; chat integration only
  creates pending proposals and grants no execution authority.
  This is not a durable exactly-once guarantee or a multi-user permissions framework.

Tools expose only name, description and input schema. Handlers are trusted
explicit backend registrations, never supplied by the LLM or dynamically imported.

## Dependency direction

```text
agent/tool_calls -> schema-only registry + pure routing preparation -> contracts
conversations/service -> pure routing preparation; receives registration callback
api/conversations + api/actions -> api/action_runtime -> SAME owner-scoped service
api/actions -> owner-scoped service -> approval -> contracts
api/actions supplies execution resources -> executor -> approval + registry/tools -> contracts
activity_tool -> planner/activity_service -> existing CRUD
future response-planning implementation -> ResponsePlanner interface
```

Core `ai/actions` modules do not import the agent reasoner, context selection,
observations, memory, HTTP, SQLite, planner CRUD or OpenAI. The activity adapter
delegates to an existing planner service; no reverse imports/cycles were added.
Architecture tests allow only two exact adapter-module exceptions:
`ai/actions/activity_tool.py` may import `planner/activity_service.py`, and
future `ai/actions/exam_tool.py` may import `planner/exam_service.py`. The activity
adapter is implemented; the exam adapter is not. Other action modules remain unable to import
planner services; even these adapters cannot import raw CRUD/database, HTTP,
reasoning, context, observation or memory modules. Planner services must not import
the action layer. This keeps the future delegation direction explicit and acyclic.

## Offline tests

From the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_action_contracts -v
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_action_layer -v
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_add_activity_tool -v
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_action_approval_api -v
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_llm_action_proposals -v
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -q
```

Core checks use fake tools. The add-activity tests also exercise the real service
and CRUD using in-memory/temporary SQLite databases, never the project database.
There are no paid OpenAI calls. They
cover pending/approved/rejected lifecycle, no automatic execution, forged snapshots,
strict tool/schema validation, unknown tools, concurrent/repeated execution,
safe failures, JSON results, response-plan placeholders and existing schema/import
compatibility, approved creation/persistence, domain validation, refused pending/rejected
creation and no duplicate replay, owner isolation, argument tampering, status refresh,
concurrent confirmations and the opt-in sample source. Frontend `npm test` covers
the actual generic card and hook; `npm run build` and `npm run lint` check integration.
Exam/edit/delete tools, persistent proposals, complex planning and loops
are intentionally left for later stages.
