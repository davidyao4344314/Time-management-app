# Stage 8: Action Layer structure

This stage establishes contracts and trusted backend boundaries only. The normal
AI request still returns its existing message/actions proposal format and never
executes a planner tool. There are no approval HTTP routes or confirmation UI yet.

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
                                  -> explicit user decision (future HTTP/UI adapter)
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
adapter can pass its validated result to this router after the real confirmation
workflow is added. No new layer is automatically invoked by today's chat path.

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
  restart loses it. No UI/API can approve or execute it in this stage. A future
  HTTP adapter must enforce authenticated owner/conversation access, persist
  proposals/decisions as needed, and never accept client-supplied approved objects.
  This is not a production execution endpoint or a durable exactly-once guarantee.

Tools expose only name, description and input schema. Handlers are trusted
explicit backend registrations, never supplied by the LLM or dynamically imported.

## Dependency direction

```text
future agent/service adapter -> routing -> registry/tools + approval -> contracts
future explicit approval adapter -> approval -> contracts
future execution adapter -> executor -> approval + registry/tools -> contracts
future response-planning implementation -> ResponsePlanner interface
```

Nothing in `ai/actions` imports the agent reasoner, context selection, observations,
memory, HTTP, SQLite, planner CRUD or OpenAI. No reverse imports/cycles were added.
Later trusted tool handlers can delegate to existing planner services without
putting SQL, approval decisions or model reasoning into the tools' public contracts.

## Offline tests

From the project root:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_action_contracts -v
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_action_layer -v
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -q
```

These checks use fake tools, not real planner writes or paid OpenAI calls. They
cover pending/approved/rejected lifecycle, no automatic execution, forged snapshots,
strict tool/schema validation, unknown tools, concurrent/repeated execution,
safe failures, JSON results, response-plan placeholders and existing schema/import
compatibility. Real Activity/Exam tool execution, persistent proposals, approval
endpoints/UI, complex planning and loops are intentionally left for later stages.
