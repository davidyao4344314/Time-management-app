# Stage 8: Action Layer, approved creation and user confirmation

This stage establishes contracts and trusted backend boundaries. Commit 8.2 adds
an explicitly opted-in real `add_activity` tool using the existing service. The normal
AI request still returns its existing message/actions proposal format and never
executes a planner tool. Commit 8.3 adds a generic approval UI/API for manually
created backend proposals; chat/model output is still not connected to it.

## Structure and responsibility

```text
backend/app/ai/actions/
├── __init__.py       # Package description; no initialization side effects
├── contracts.py      # Existing add-activity schema + routes, proposals/results/statuses
├── tools.py          # Tool public contract, strict input validation, optional trusted handler
├── registry.py       # Explicit tool registration/discovery; proposal-only default registry
├── routing.py        # Existing agent output -> validated pending proposals or reserved route
├── approval.py       # Backend-held temporary lifecycle; explicit approve/reject decisions
├── execution.py      # Approved ID -> trusted tool -> ActionResult
├── activity_tool.py  # Opt-in AddActivityTool -> existing Activity service
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

The current agent/API/SDK schema is intentionally unchanged. A future service
adapter can pass its validated result to this router in a later step.
No new layer is automatically invoked by today's chat path.

## Commit 8.2: approved activity creation

`AddActivityTool(connection)` is a trusted `Tool` adapter. The caller owns the
SQLite connection and explicitly opts in using `create_activity_tool_registry(connection)`.
It registers only `add_activity` through the existing `ToolRegistry`. The default
`create_proposal_tool_registry()` remains non-executable. Constructing either
registry creates no database rows and opens no connection.

The public input remains `AddActivityArguments`: `name`, `category`, `subject`,
`activity_type`, `date`, `weekday`, `start_time`, `end_time`. All keys are required;
unused/optional values are null. It does not expose source/external IDs, active
date ranges, SQL, paths or persistence objects. No schema is sent to an LLM.

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
confirmation below, but no chat/LLM integration, exam/edit/delete tool or durable
approval storage is added.
Handler/service failures use the existing sanitized unconfirmed-outcome behavior;
a failed post-insert read must not be reported as proof that no row was created.

## Commit 8.3: generic Confirm / Cancel flow

The AI Agent page has a **Proposed changes** panel. `ActionProposalCard` displays
the backend's title, description and status without inspecting tool names. It
never calls the activity API to create data. Existing AI response actions remain
proposal text in the context inspector; they do not become executable proposals yet.

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
before making another decision. Failed tool results retain the existing warning
that state might have changed; a failure does not promise rollback.

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
  `Execution is not available for this tool.` No exam/edit/delete tools exist.
- Approval state is temporary and instance-scoped, not persistent or global. A
  restart loses it. The generic HTTP adapter enforces signed profile ownership,
  never accepts client-supplied approved objects, and only executes through the
  existing boundary. Persistent proposals and chat/model integration remain deferred.
  This is not a durable exactly-once guarantee or a multi-user permissions framework.

Tools expose only name, description and input schema. Handlers are trusted
explicit backend registrations, never supplied by the LLM or dynamically imported.

## Dependency direction

```text
future agent/service adapter -> routing -> registry/tools + approval -> contracts
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
LLM wiring, exam/edit/delete tools, persistent proposals, complex planning and loops
are intentionally left for later stages.
