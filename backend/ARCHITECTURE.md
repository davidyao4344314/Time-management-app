# Backend architecture

This is a behavior-preserving refactor, not a new memory or planning feature.
The existing API entry point is still `backend.fastapi_test:app`. Activities
and exams still use the same SQLite database and CRUD functions.

## Normal request flow

```text
React -> api/ai.py -> agent/service.py
                        |
                        +-> context/selection.py -> keywords / intent / fallback
                        +-> observations/collect.py -> activities / exams -> existing CRUD/calendar
                        +-> agent/reasoning.py -> OpenAI -> validated proposal
api/ai.py -> memory/recent.py -> memory/archive_store.py when the recent limit is exceeded
```

Observations are current factual application data. Recent memory is conversation
context. They stay separate. Archived and durable memory are not automatically
retrieved or included in the normal prompt. Proposed actions are not executed.

## File tree and responsibilities

```text
backend/
├── fastapi_test.py          # Existing ASGI entry point and non-AI HTTP routes
├── README.md
├── ARCHITECTURE.md
└── app/
    ├── activities.py        # Existing activity SQL/CRUD; unchanged
    ├── exams.py             # Existing exam SQL/CRUD; unchanged
    ├── database.py          # Existing connection/schema logic; unchanged
    ├── calender.py          # Existing recurrence/calendar logic; unchanged
    ├── ai_config.py         # Existing local settings/key configuration; unchanged
    ├── activity_service.py  # Add/edit validation and reuse of existing CRUD
    ├── actions/
    │   └── contracts.py     # Allowed proposal arguments, not execution
    ├── agent/
    │   ├── contracts.py     # AgentProposal and validation
    │   ├── service.py       # Coordinate a proposal request
    │   └── reasoning.py     # Prompt, message construction and model response
    ├── api/
    │   └── ai.py            # AI HTTP requests/errors, read-only DB lifetime, cookies
    ├── context/
    │   ├── keywords.py      # Existing Stage 1 routing
    │   ├── intent.py        # Existing Stage 2 classification and routing schemas
    │   ├── fallback.py      # Existing Stage 3 fallback classification
    │   └── selection.py     # Stop at the first confident route; safe fallback
    ├── observations/
    │   ├── formatting.py    # Shared time/date formatting and ordering
    │   ├── activities.py    # Compact activity/calendar scopes
    │   ├── exams.py         # Compact upcoming assessments
    │   ├── screen_time.py   # Existing formatter; not added to agent requests
    │   └── collect.py       # Build only the selected activity/exam sections
    ├── memory/
    │   ├── contracts.py     # Memory request, archive and durable-memory schemas
    │   ├── paths.py         # Stable paths to existing ignored memory files
    │   ├── settings.py      # Archive threshold and candidate batch size
    │   ├── records.py       # Pure serialization, hashes, IDs and timestamps
    │   ├── recent.py        # In-process per-session recent turns
    │   ├── archive_store.py # Raw-turn append/read, count and shared archive lock
    │   ├── selection.py     # Threshold diagnostic and oldest candidate selection
    │   ├── protection.py    # Deterministic candidate protection
    │   ├── classification.py # Model classification of uncertain candidates
    │   ├── summary.py       # Model summaries of confirmed compactable candidates
    │   ├── category_policy.py # Pure category acceptance safeguards
    │   ├── category_review.py # Model review plus application of accepted categories
    │   ├── compaction_plan.py # Pure validation, replacement bytes and dry-run preview
    │   ├── compaction.py    # Locked, verified backup/replacement/recovery
    │   ├── durable.py       # Model extraction from explicitly supplied protected turns
    │   ├── durable_store.py # Conservative deduplication and verified durable-file writes
    │   └── search.py        # Existing bounded, session-scoped raw archive search
    ├── infrastructure/
    │   ├── atomic_files.py  # Regular-file checks, locking, private temps and fsync
    │   ├── errors.py        # Shared safe utility error
    │   ├── privacy.py       # Secret redaction
    │   └── module_compat.py # Temporary legacy-name forwarding
    └── dev/
        ├── memory_debug.py # Standalone fake-data trace; not called by normal requests
        └── observation_smoke.py # Existing explicit observation receipt test
```

Package `__init__.py` files contain descriptions only; they do not initialize
stores or call models. Legacy wrapper files are omitted from this tree.

## Function ownership

| Owner | Functions / contracts | Keep out |
| --- | --- | --- |
| `memory/recent.py` | `has_session`, `get_recent_turns`, `add_completed_turn`, recent deque/lock | Raw file-write implementation, model reasoning |
| `memory/archive_store.py` | `archive_write_lock`, `append_archived_turn`, `iter_archived_turns`, `get_archive_turn_count` | Recent session state, summarization, model calls |
| `memory/selection.py` | `archive_needs_compaction`, `select_archive_compaction_candidates`, size reporting | Archive replacement, model calls |
| `memory/protection.py` | `classify_archive_candidate`, `classify_compaction_candidates`, protection rules | Model calls or deletion |
| `memory/classification.py` | `classify_uncertain_archive_candidates` and its small model request | Reading/replacing the live archive |
| `memory/summary.py` | `summarize_compactable_archive_turns` | Archive replacement or durable extraction |
| `memory/category_policy.py` | Category name, synonym and protected-content safeguards | Model/configuration calls or persistence |
| `memory/category_review.py` | Existing category review and in-memory summary redistribution | Raw archive deletion |
| `memory/compaction_plan.py` | `prepare_compaction`, `preview_compacted_archive`, source/final-state validation | File I/O, models, choosing protection labels |
| `memory/compaction.py` | `persist_compacted_archive`, locked verified writes and recovery | Summarization or new classification |
| `memory/durable.py` | `extract_durable_memories`, protected-source/extraction validation | Implementing file replacement |
| `memory/durable_store.py` | Conservative content keys, provenance merging, lock/persistence | OpenAI calls, reading the raw archive |
| `memory/search.py` | `resolve_time_reference`, `search_archived_memory` | Automatic retrieval, summaries or main-agent calls |
| `observations/activities.py` | `build_activity_observation` | New recurrence rules or memory storage |
| `observations/exams.py` | `build_exam_observation` | Activity recurrence, calendar changes |
| `observations/screen_time.py` | Existing `build_screen_time_observation` | New agent routing or tracking |
| `observations/formatting.py` | `compact_time`, `chronological_key`, `observation_date_range` | SQL or model calls |
| `observations/collect.py` | `collect_agent_observations` | Deciding intent or formatting conversation history |
| `context/selection.py` | `select_agent_context`, Stage 1/2/3 ordering | Building observations, answering the user |
| `context/keywords.py` | `choose_agent_context`, `assess_stage_one` | LLM calls |
| `context/intent.py`, `fallback.py` | Existing strict classification models and small classifier calls | Full observations, advice or tool execution |
| `agent/service.py` | `get_agent_proposal`: key/settings checks, client lifetime, routing/collection | Archive compaction, SQL writes or executing proposals |
| `agent/reasoning.py` | Prompt, `build_agent_messages`, request budgets, model request/response parsing | CRUD, archive reading, recurrence |
| `api/ai.py` | Existing AI routes, HTTP errors, read-only connection and session-cookie handling | Planning prompt or activity SQL |
| `activity_service.py` | `prepare_new_activity`, `create_activity_record`, `validate_activity_edit`, `update_activity_record` | HTTP dependencies, agent approval/execution |
| `infrastructure/` | Shared file checks/atomic writes, safe errors, redaction and compatibility forwarding | Agent/domain decisions |

The three contract modules contain validation/schema definitions, not tool
handlers. `memory/contracts.py` also owns the durable-memory models; their
validation semantics were retained.

## Moves and compatibility

| Previous module | Canonical implementation |
| --- | --- |
| `ai_memory.py` | `memory/recent.py`, `archive_store.py`, `selection.py`, `settings.py` |
| `ai_archive_protection.py` | `memory/protection.py` |
| `ai_archive_llm_classifier.py` | `memory/classification.py` |
| `ai_archive_summary.py` | `memory/summary.py` |
| `ai_archive_category_review.py` | `memory/category_review.py` and `category_policy.py` |
| `ai_archive_persistence.py` | `memory/compaction.py` and `compaction_plan.py` |
| `ai_durable_memory.py` | `memory/durable.py`, `durable_store.py` and `contracts.py` |
| `ai_archive_search.py` | `memory/search.py` |
| `ai_context_router.py` | `context/keywords.py` |
| `ai_intent_classifier.py` | `context/intent.py` |
| `ai_stage_three_router.py` | `context/fallback.py` |
| `ai_routing_pipeline.py` | `context/selection.py` |
| `activity_observation.py`, `exam_observation.py` | `observations/activities.py`, `exams.py` |
| `screen_time_observation.py`, `observation_utils.py` | `observations/screen_time.py`, `formatting.py` |
| `ai_proposal.py` | `agent/service.py`, `reasoning.py` and shared contracts |
| AI handlers in `backend/fastapi_test.py` | `api/ai.py`; mounted on the original app |
| Activity add/edit validation in `backend/fastapi_test.py` | `activity_service.py`; same manual HTTP endpoints |
| `memory_debug.py`, `ai_observation_test.py` | `dev/memory_debug.py`, `observation_smoke.py` |

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

## Import direction and safety

- HTTP adapters import services, not the other way around.
- Agent coordination imports routing, collectors and the reasoner.
- Routing does not import observation builders, CRUD or archive files.
- Observations import current calendar/CRUD functions, never the main agent.
- Recent memory imports archive storage/selection; storage does not import recent memory.
- Pure compaction planning imports record helpers/contracts/category policy, not persistence.
- Durable extraction imports storage; storage does not import the extractor or SDK.
- Contracts and infrastructure do not import model callers or HTTP modules.
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

No new action executor was created: the agent still only proposes
`add_activity`. Existing activity edits still call `edit_activity` in the same
sequence, with its existing commit behavior. Create returns the ID from the
existing `add_activity` and reads the row through `get_activity_by_id` rather than
repeating SELECT logic in the HTTP layer.

## Verification and unchanged behavior

Run from the project root:

```bash
backend/.venv/bin/python -B -m unittest discover -s backend -p 'test_*.py'
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

## Future extensions (not implemented)

- **Stage 7 retrieval:** a separate coordinator can combine bounded search and
  durable/summary retrieval without changing recent-memory storage.
- **Screen Time:** add a selected collector section and routing rule using the
  existing formatter, without rewriting main-agent history formatting.
- **Additional tools:** extend action contracts, then add a distinct approval and
  execution layer. Never execute actions inside proposal generation.
- **Edit/delete proposals:** call the validated activity service/existing CRUD
  only after explicit approval; protect source/external IDs and UoA mappings.
