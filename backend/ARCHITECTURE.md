# Backend architecture

The package organization is a behavior-preserving refactor. The boundary fixes
documented below add targeted safety/correctness changes. Stage 7 now extends
the existing routing/observation pipeline with bounded read-only memory retrieval.
The canonical API entry point is `backend.app.server:app`;
`backend.fastapi_test:app` remains a compatibility entry point to the same app.
Activities and exams still use the same SQLite database and CRUD functions.

## Normal request flow

```text
React -> api/conversations.py -> conversations/service.py
                                    | -> storage.py: pending/completed messages
                                    | -> context.py: recent turns/local summary
                                    | -> memory_context.py: owner-authorized retrieval
                                    v
                               ai/agent/service.py
                        |
                        +-> ai/context/selection.py -> keywords / intent / fallback
                        +-> ai/observations/collect.py -> activities / exams -> existing CRUD/calendar
                        +-> ai/agent/reasoning.py -> OpenAI -> validated proposal
conversations/service.py -> memory_export.py -> archive_store.py for opted-in older turns

Compatibility only: api/ai.py -> ai/memory/recent.py -> archive_store.py
```

Observations are current factual application data. Recent memory is conversation
context. They stay separate. Archived and durable memory are retrieved only when
selected by routing or a bounded missing-context request, never sent wholesale.
Proposal generation does not execute actions. Stage 8.4 normalizes native model
function calls into pending proposals. A separate user Confirm uses the existing
approval-gated executor; Cancel changes no planner data.

## File tree and responsibilities

```text
backend/
├── fastapi_test.py              # Compatibility entry point/exports
├── README.md
├── ARCHITECTURE.md
├── requirements.txt
├── .venv/
├── tests/
│   ├── ai/                     # Proposal, routing, HTTP and observation tests
│   │   └── memory/             # Archive/compaction/durable/debug stage tests
│   ├── planner/                # Activity service, current/next, source and UID
│   ├── integrations/           # Import deduplication and UoA date ranges
│   ├── screen_time/            # Summary storage/formatting checks
│   ├── paths.py                # Test repository paths
│   ├── test_architecture.py    # Import graph/boundary checks
│   ├── test_refactor_boundaries.py
│   └── test_folder_layout.py   # Relocation/entry point/path compatibility
└── app/
    ├── server.py               # FastAPI assembly, no business logic
    ├── cli.py                  # Existing interactive planner CLI
    ├── database.py             # Planner connection/schema setup
    ├── conversations/
    │   ├── contracts.py        # Chat requests, responses and safe errors
    │   ├── storage.py          # All chat SQL, summary reservations, export receipts
    │   ├── service.py          # Request orchestration; no business SQL
    │   ├── context.py          # Bounded recent turn excerpts and local summary
    │   ├── summary.py          # Explicit local-summary model coordination
    │   ├── memory_context.py   # Authorized local/global read-only retrieval
    │   ├── memory_export.py    # Retry-safe archive handoff
    │   └── legacy.py           # Verified legacy adoption through storage
    ├── ai/
    │   ├── config.py           # Existing local key/model/context configuration
    │   ├── actions/
    │   │   ├── contracts.py    # Existing arguments + generic routes/proposals/results/statuses
    │   │   ├── tools.py        # Public schemas and optional trusted tool handlers
    │   │   ├── registry.py     # Explicit discovery; default tools are proposal-only
    │   │   ├── routing.py      # Validated agent output -> pending proposal(s); no execution
    │   │   ├── approval.py     # Temporary authoritative approve/reject lifecycle
    │   │   ├── execution.py    # Approved ID -> trusted registry -> result
    │   │   ├── activity_tool.py # Opt-in AddActivityTool -> existing Activity service
    │   │   ├── service.py      # Owner-scoped views/decisions; temporary approval state
    │   │   └── planning.py     # ResponsePlanner interface, not implemented
    │   ├── agent/
    │   │   ├── contracts.py    # AgentProposal and validation
    │   │   ├── service.py      # Coordinate a proposal request
    │   │   ├── tool_calls.py   # Native Responses calls -> schema-validated requests; no execution
    │   │   └── reasoning.py    # Prompt, model messages and response
    │   ├── context/
    │   │   ├── keywords.py     # Stage 1 routing
    │   │   ├── intent.py       # Stage 2 classification/schemas
    │   │   ├── fallback.py     # Stage 3 fallback classification
    │   │   ├── selection.py    # First confident route; safe fallback
    │   │   ├── profiles.py     # Shared classification -> selection adapter
    │   │   └── adaptive/       # Opt-in reviewed routing evidence/patterns/examples/metrics
    │   ├── observations/
    │   │   ├── formatting.py   # Shared time/date formatting and ordering
    │   │   ├── activities.py   # Compact activity/calendar scopes
    │   │   ├── exams.py        # Compact upcoming assessments
    │   │   ├── screen_time.py  # Existing formatter; not in agent requests
    │   │   └── collect.py      # Only selected activity/exam sections
    │   ├── memory/
    │   │   ├── contracts.py    # Request, archive and durable schemas
    │   │   ├── paths.py        # Existing ignored file locations
    │   │   ├── settings.py     # Threshold and candidate batch size
    │   │   ├── records.py      # Serialization, hashes, IDs/timestamps
    │   │   ├── search_helpers.py # Shared pure matching/timestamp/excerpt helpers
    │   │   ├── recent.py       # In-process per-session recent turns
    │   │   ├── session_identity.py # Restart-safe signed conversation cookies
    │   │   ├── archive_store.py # Raw append/read/count and shared lock
    │   │   ├── selection.py    # Threshold and oldest candidate selection
    │   │   ├── protection.py   # Deterministic candidate protection
    │   │   ├── classification.py # Uncertain candidate model classification
    │   │   ├── summary.py      # Confirmed candidate model summaries
    │   │   ├── category_policy.py # Pure category safeguards
    │   │   ├── category_review.py # Review and accepted categories
    │   │   ├── compaction_plan.py # Pure validation/replacement/preview
    │   │   ├── compaction.py   # Verified backup/replacement/recovery
    │   │   ├── durable.py      # Protected-turn model extraction
    │   │   ├── durable_store.py # Deduplication/verified file writes
    │   │   └── search.py       # Bounded, session-scoped archive search
    │   └── compat/             # Name forwarding for older split facades
    ├── planner/
    │   ├── activities.py       # Existing activity SQL/CRUD
    │   ├── activity_service.py # Existing add/edit validation/use cases
    │   ├── exams.py            # Existing exam SQL/CRUD
    │   ├── exam_service.py     # Exam preparation/edit validation and updates
    │   └── calendar.py         # Existing recurrence/calendar logic
    ├── screen_time/
    │   └── storage.py          # Existing daily summary CRUD
    ├── integrations/
    │   ├── ical_import.py      # Shared download/VEVENT parsing
    │   ├── canvas_import.py    # Canvas classification/conversion/import
    │   └── uoa_timetable_import.py # Grouped weekly classes and UID mapping
    ├── api/
    │   ├── ai.py              # AI HTTP, read-only DB and session cookies
    │   ├── activities.py      # Manual activity CRUD HTTP endpoints
    │   ├── exams.py           # Exam CRUD HTTP endpoints
    │   ├── calendar.py        # Today/current/week/move HTTP endpoints
    │   ├── imports.py         # Canvas/UoA status/import HTTP endpoints
    │   ├── actions.py         # Generic proposal list/decision APIs; opt-in sample source
    │   ├── action_runtime.py  # Shared proposal service and explicit-confirm execution resources
    │   └── common.py          # Existing row formatting/time adapters
    ├── infrastructure/
    │   ├── paths.py           # Stable project/backend locations
    │   ├── clock.py           # Shared Pacific/Auckland clock
    │   ├── atomic_files.py    # Regular files, locks, private temps and fsync
    │   ├── errors.py          # Shared safe utility error
    │   ├── privacy.py         # Secret redaction
    │   └── module_compat.py   # Temporary legacy-name forwarding
    └── dev/
        ├── memory_debug.py    # Explicit disposable fake-data trace
        ├── action_proposals.py # Opt-in pending sample, never automatic execution
        └── observation_smoke.py # Explicit observation receipt test
```

Package imports do not initialize stores or call models. Most `__init__.py`
files contain descriptions only; `screen_time/__init__.py` also forwards the
previous module's function names. Legacy wrappers are omitted from this tree.

## Function ownership

| Owner | Functions / contracts | Keep out |
| --- | --- | --- |
| `ai/memory/recent.py` | `has_session`, `get_recent_turns`, `add_completed_turn`, recent deque/lock | Raw file-write implementation, model reasoning |
| `ai/memory/archive_store.py` | `archive_write_lock`, `append_archived_turn`, `iter_archived_turns`, `get_archive_turn_count` | Recent session state, summarization, model calls |
| `ai/memory/selection.py` | `archive_needs_compaction`, `select_archive_compaction_candidates`, size reporting | Archive replacement, model calls |
| `ai/memory/protection.py` | `classify_archive_candidate`, `classify_compaction_candidates`, protection rules | Model calls or deletion |
| `ai/memory/classification.py` | `classify_uncertain_archive_candidates` and its small model request | Reading/replacing the live archive |
| `ai/memory/summary.py` | `summarize_compactable_archive_turns` | Archive replacement or durable extraction |
| `ai/memory/category_policy.py` | Category name, synonym and protected-content safeguards | Model/configuration calls or persistence |
| `ai/memory/category_review.py` | Existing category review and in-memory summary redistribution | Raw archive deletion |
| `ai/memory/compaction_plan.py` | `prepare_compaction`, `preview_compacted_archive`, source/final-state validation | File I/O, models, choosing protection labels |
| `ai/memory/compaction.py` | `persist_compacted_archive`, locked verified writes and recovery | Summarization or new classification |
| `ai/memory/durable.py` | `extract_durable_memories`, protected-source/extraction validation | Implementing file replacement |
| `ai/memory/durable_store.py` | Conservative content keys, provenance merging, lock/persistence | OpenAI calls, reading the raw archive |
| `ai/memory/search.py` | `resolve_time_reference`, `search_archived_memory` | Automatic retrieval, summaries or main-agent calls |
| `ai/observations/activities.py` | `build_activity_observation` | New recurrence rules or memory storage |
| `ai/observations/exams.py` | `build_exam_observation` | Activity recurrence, calendar changes |
| `ai/observations/screen_time.py` | Existing `build_screen_time_observation` | New agent routing or tracking |
| `ai/observations/formatting.py` | `compact_time`, `chronological_key`, `observation_date_range` | SQL or model calls |
| `ai/observations/collect.py` | `collect_agent_observations` | Deciding intent or formatting conversation history |
| `ai/context/selection.py` | `select_agent_context`, Stage 1/2/3 ordering | Building observations, answering the user |
| `ai/context/keywords.py` | `choose_agent_context`, `assess_stage_one` | LLM calls |
| `ai/context/adaptive/store.py` | Owner-scoped routing evidence/labels/patterns, atomic audit reservations | Planner CRUD, model calls, automatic truth labels |
| `ai/context/adaptive/learning.py` | Completed telemetry, explicit review/approval, scoped snapshots | Observation formatting, action execution |
| `ai/context/adaptive/patterns.py`, `examples.py`, `metrics.py` | Pure phrase statistics/matching, bounded reviewed examples, measured agreement | SQL, model calls, factual app state |
| `ai/context/intent.py`, `fallback.py` | Existing strict classification models and small classifier calls | Full observations, advice or tool execution |
| `ai/agent/service.py` | `get_agent_proposal`: key/settings checks, client lifetime, routing/collection | Archive compaction, SQL writes or executing proposals |
| `ai/agent/reasoning.py` | Prompt, `build_agent_messages`, request budgets, model request/response parsing | CRUD, archive reading, recurrence |
| `api/ai.py` | Existing AI routes, HTTP errors, read-only connection and session-cookie handling | Planning prompt or activity SQL |
| `planner/activity_service.py` | `prepare_new_activity`, `create_activity_record`, `validate_activity_edit`, `update_activity_record` | HTTP dependencies, agent approval/execution |
| `infrastructure/` | Shared file checks/atomic writes, safe errors, redaction and compatibility forwarding | Agent/domain decisions |

The three contract modules contain validation/schema definitions, not tool
handlers. `ai/memory/contracts.py` also owns the durable-memory models; their
validation semantics were retained.

## Moves and compatibility

| Previous module | Canonical implementation |
| --- | --- |
| `ai_memory.py` | `ai/memory/recent.py`, `archive_store.py`, `selection.py`, `settings.py` |
| `ai_archive_protection.py` | `ai/memory/protection.py` |
| `ai_archive_llm_classifier.py` | `ai/memory/classification.py` |
| `ai_archive_summary.py` | `ai/memory/summary.py` |
| `ai_archive_category_review.py` | `ai/memory/category_review.py` and `category_policy.py` |
| `ai_archive_persistence.py` | `ai/memory/compaction.py` and `compaction_plan.py` |
| `ai_durable_memory.py` | `ai/memory/durable.py`, `durable_store.py` and `contracts.py` |
| `ai_archive_search.py` | `ai/memory/search.py` |
| `ai_context_router.py` | `ai/context/keywords.py` |
| `ai_intent_classifier.py` | `ai/context/intent.py` |
| `ai_stage_three_router.py` | `ai/context/fallback.py` |
| `ai_routing_pipeline.py` | `ai/context/selection.py` |
| `activity_observation.py`, `exam_observation.py` | `ai/observations/activities.py`, `exams.py` |
| `screen_time_observation.py`, `observation_utils.py` | `ai/observations/screen_time.py`, `formatting.py` |
| `ai_proposal.py` | `ai/agent/service.py`, `reasoning.py` and shared contracts |
| AI handlers in `backend/fastapi_test.py` | `api/ai.py`; mounted on the original app |
| Activity add/edit validation in `backend/fastapi_test.py` | `planner/activity_service.py`; same manual HTTP endpoints |
| `memory_debug.py`, `ai_observation_test.py` | `dev/memory_debug.py`, `observation_smoke.py` |
| Old `agent/`, `context/`, `observations/`, `memory/`, `actions/` | Corresponding packages under `ai/`; old paths alias canonical owners |
| `ai_config.py` | `ai/config.py` |
| `activities.py`, `activity_service.py`, `exams.py` | Corresponding modules under `planner/` |
| `calender.py` | `planner/calendar.py` (spelling corrected) |
| `screen_time.py` | `screen_time/storage.py`; package exports and old manual script stay compatible |
| Canvas, UoA and generic iCal modules | Corresponding modules under `integrations/` |
| Non-AI handlers in `backend/fastapi_test.py` | `api/activities.py`, `exams.py`, `calendar.py`, `imports.py`, `common.py` |
| FastAPI app assembly | `server.py`; original entry point forwards to the same instance |
| `main.py` | `cli.py`; old script forwards to `main()` |
| `backend/test_*.py` | Feature groups under `backend/tests/` |

Old module names remain compatibility wrappers. Whole-module moves alias the
same module object. Split modules use name forwarding so state, paths and test
patches refer to the real owner instead of a second copy. Supported existing
explicit imports and CLI commands continue working. New application code should
use canonical modules, not depend on a legacy facade. The standalone fake-data
debug utility deliberately retains two forwarding facades for its temporary
multi-module patches; it does not create another store.

Do not remove wrappers until downstream scripts/tests have migrated. Moving a
function is not permission to change its prompt, recurrence rules, schema or
error response. Existing logger names were retained for compatibility.

## Stable data paths

`infrastructure/paths.py` defines the project and backend directories. Relocated
config/import/memory modules use these constants rather than depending on their
new folder depth. These files stay in place:

- Project-root `.env` (and any existing `.env.save`)
- `backend/study_app.db` and project-root `activities.sql`
- `backend/ai_memory_archive.jsonl`
- `backend/ai_durable_memories.json`

The earlier grouping did not migrate schemas or copy secrets. The opt-in
adaptive-routing feature now creates three learning tables in the same existing
SQLite database when the conversation service opens it. It does not change
planner tables, move archives, or store API keys. See the README for defaults,
review gates and no-charge evaluation.

## Import direction and safety

- `server.py` assembles routers; routers never import the server/legacy entry point.
- HTTP adapters import services, not the other way around.
- `planner/`, `screen_time/` and `integrations/` do not import AI or HTTP layers.
- Agent coordination imports routing, collectors and the reasoner.
- Routing does not import observation builders, CRUD or archive files.
- Observations import current calendar/CRUD functions, never the main agent.
- Recent memory imports archive storage/selection; storage does not import recent memory.
- Pure compaction planning imports record helpers/contracts/category policy, not persistence.
- Durable extraction imports storage; storage does not import the extractor or SDK.
- Contracts and infrastructure do not import model callers or HTTP modules.
- Action contracts, registry, routing, approval and execution do not import planner
  services. Only `ai/actions/activity_tool.py` and the reserved future `exam_tool.py`
  adapters may import their matching `planner/activity_service.py` or `exam_service.py`.
  The exception does not allow raw CRUD/database imports or reverse planner-to-AI imports,
  and does not connect tool execution to the agent reasoner. The HTTP action adapter
  shares `api/action_runtime.py` with the conversation adapter. Chat receives a
  registration callback for newly completed requests; only explicit Confirm
  opens execution resources. The reasoner imports schema-only contracts, not handlers.
- The explicit `/ai/test-observation` diagnostic uses the receipt-test utility;
  normal proposals do not run the developer memory trace.

Architecture tests detect local import cycles and enforce these core boundaries.
Avoid reverse imports to a facade: they can conceal cycles and copied state.

## Completed implementation steps and why

Steps 2–3 were already committed before this batch.

| Step | Change | Why |
| --- | --- | --- |
| 1 | Baseline regression checks; no production change | Establish existing behavior before moving code |
| 2 | Shared action, agent and memory contracts | One owner for formats/validation |
| 3 | Shared file, record, path and privacy utilities | Remove cross-stage utility dependencies |
| 4 | Recent sessions separate from archive storage/selection | Separate temporary context from disk history |
| 5 | Dedicated archive stage modules and pure category policy | Separate deterministic safeguards from model review |
| 6 | Pure compaction planning separate from persistence | Preview and writes share validation; storage stays independently testable |
| 7 | Durable extraction/contracts separate from durable storage | File operations do not depend on OpenAI |
| 8 | Context and observation packages plus a collector | Routing chooses what; observations build facts |
| 9 | Agent orchestration separate from model reasoning | Reuse data collection without coupling it to prompts or tools |
| 10 | AI routes and developer utilities extracted | HTTP/session handling and developer tests have explicit homes |
| 11 | Existing activity validation/use cases extracted | Future approved tools can reuse validation and CRUD without copying HTTP code |
| 12 | Documentation, compatibility and dependency checks | Make ownership visible and prevent regressions |

The original refactor created no action executor. Stage 8 now provides an
approval-gated executor and an explicitly registered real `AddActivityTool`,
with generic owner-scoped HTTP/UI confirmation for native model and development
proposals. The normal agent only requests `add_activity`, never approves/executes
it. Proposal state remains temporary and is not reconstructed from saved chat
after restart. Activity edits still call `edit_activity` in the same sequence,
now within one savepoint so a failed logical edit rolls back all its fields.
Standalone `edit_activity` callers still commit by default. Create returns the ID from the
existing `add_activity` and reads the row through `get_activity_by_id` rather than
repeating SELECT logic in the HTTP layer.

## Verification and unchanged behavior

Run from the project root:

```bash
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -p 'test_*.py'
backend/.venv/bin/python -B -m backend.app.dev.memory_debug --stage all --skip-llm
```

The old `backend.app.memory_debug` command remains valid. The debug command uses
disposable fake files; without `--llm` it makes no paid calls. Model-calling tests
mock the SDK. Database tests use disposable/in-memory data, not the project DB.

The full OpenAPI schema was compared before and after route/service extraction;
the paths, request schemas and responses are unchanged. The regression suite
covers nullable times, import IDs/source metadata, recurrence, observation scopes,
routing fallbacks, session isolation/limits, safe archive replacement/recovery,
durable deduplication and refusal to execute proposed actions.

An additional one-off baseline comparison exercised 170 add/edit cases against
the pre-refactor handlers using in-memory SQLite. Success results, validation
errors and resulting rows matched for Manual, Canvas and UoA records.

No frontend files, database schema, SQLite rows, Canvas/UoA import behavior,
local environment configuration, production archives or durable store contents
were changed. No live OpenAI call is necessary for this refactor's tests.

## Running the grouped backend

From the project root:

```bash
backend/.venv/bin/python -m uvicorn backend.app.server:app --reload --port 8001
```

The old `backend.fastapi_test:app` command remains valid. Tests now use
`backend.tests...` import paths; for example:

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_ai_proposal -v
```

The full OpenAPI schema was checked again after grouping the feature routers.
All 23 API paths, request schemas and response contracts are unchanged.

## Review boundary fixes

- Compaction selects up to the configured batch size from one identified
  session, advancing past protected-only chats/prefixes when other work exists.
  An optional `after_session_id` supports explicit advancement. Stage 4 and persistence
  reject mixed-session or unidentified summaries. Protected-turn rules are unchanged.
- Chat storage owns summary reservations/persistence, export receipts and legacy
  inserts. Orchestrators do not embed business SQL. Planner database initialization
  does not import conversation modules; the conversation service initializes its tables.
- Architecture tests enforce conversation import/SQL boundaries and the acyclic
  import graph alongside the existing routing, observation and infrastructure rules.
- `iter_archive_records(session_id=...)` is the shared read-only archive interface.
  It excludes ambiguous/mixed-session legacy summaries from scoped reads without
  deleting them. Raw and summary search reuse this reader.
- `get_recent_turns` returns a bounded snapshot without writes. The request handler
  explicitly calls `enforce_recent_limit` first. Archival succeeds before eviction;
  memory I/O errors return a generic HTTP error without exposing file contents.
- Conversation ownership is authenticated with a second HttpOnly signature cookie,
  independently of the in-memory deque. `backend/.ai_session_key` is generated
  locally on first use with private permissions, persists across server restarts,
  and is Git-ignored together with its lock file. Never publish or delete that key
  casually: deleting it invalidates existing cookie signatures. Existing unsigned
  cookies receive a new identity once; old archive records are retained, not claimed
  by the new identity. Recent turns remain in RAM and are not restored on restart.
- Exam-only questions about today select today's exams; study planning can still
  include upcoming exams. Stage 1 now agrees with the semantic adapter for this case.
- Exam validation/updates live in `planner/exam_service.py`. Optional exam inclusion
  in a calendar week lives in `planner/calendar.py:get_calendar_week`; HTTP routes
  retain request/response handling. Endpoint formats and recurrence are unchanged.

Regression tests use temporary files/in-memory databases and mocked models. No
production archive migration or automatic action execution is performed.

## Stage 7: routed memory observation

`context/contracts.py` shares validated selection contracts across the existing
Stage 1/2/3 cascade. The existing activity/exam fields are preserved; optional
`memory` contains allowlisted `sources` and a `query` with `time_reference` and
up to five short `search_terms`. Memory is omitted/null for ordinary requests.
No router reads storage. Clear recollection phrases take Stage 1; ambiguous or
mixed requests use the existing semantic/fallback stages.

The HTTP adapter passes its trusted session ID separately to `get_agent_proposal`.
`observations/collect.py` calls `observations/memory.py` only when selected.
`memory/search.py` reuses raw search matching and the shared archive reader, plus
a public read-only durable-store reader. It returns at most five items across
all sources within an 8,000-character observation budget, with bounded excerpts,
provenance and distinct ok/empty/partial/unavailable statuses. Missing files are
not created. Mixed-session summaries and unowned records are excluded.

Python resolves symbolic dates in Pacific/Auckland time. Raw records use turn
timestamps; durable records use supporting source dates, not extraction dates.
Summaries use period overlap and explicitly report `overlap_only`: a month-long
summary does not prove every sentence happened during the requested week.
Undated records can match topics, not date ranges. Current app observations
override old schedule claims; history is data, never action approval.

The same reasoner receives the separate recent turns and selected observations.
If its validated `memory_request` needs missing context, the service permits one
additional lookup and at most one additional main-model response. Repeated,
empty, failed or still-unresolved requests stop with clarification. Intermediate
responses are not stored as completed turns. No state-changing tools are run.

Offline checks (temporary fixtures and mocked model calls):

```bash
backend/.venv/bin/python -B -m unittest backend.tests.ai.test_memory_observation -v
backend/.venv/bin/python -B -m unittest discover -s backend/tests -t . -p 'test_*.py'
```

Optional live checks in the same signed browser conversation: ask what was
discussed last week about a known archived topic, then ask what exams are next
week. Only the first should select historical memory. Live proposal requests
use the configured OpenAI account and may incur charges. Use mocked tests first.

## Future extensions (not implemented)

- **Approved actions/re-evaluation:** add explicit approval, execution receipts,
  and bounded verification separately. Stage 7 performs no action execution.
- **Screen Time:** add a selected collector section and routing rule using the
  existing formatter, without rewriting main-agent history formatting.
- **Additional tools:** extend action contracts, then add a distinct approval and
  execution layer. Never execute actions inside proposal generation.
- **Edit/delete proposals:** call the validated activity service/existing CRUD
  only after explicit approval; protect source/external IDs and UoA mappings.
