# The Complete Lifecycle of a Single Blog Generation

**Scope:** one `POST /api/v1/blogs/generate` request traced from HTTP edge to terminal database
state — including every process boundary, every object that is created, every hop it passes
through, every field that is added, rewritten, or silently dropped, and the ORM/transaction
story underneath it all.

**Codebase:** `blogify-ai-adk-prod` @ `6b6ae2d`
**Audience:** engineers who need to reason about, debug, or modify this pipeline.

**Companion:** interactive HTML at [`docs/lifecycle/index.html`](lifecycle/index.html)
(`01-timeline`, `02-lineage`, `03-orm`, `04-findings`).

---

## 0. How to read this document

Every claim is anchored to `file_path:line_number`. Where the code and the prose docs
disagree, the code wins and the disagreement is called out.

Four lenses are used throughout, and every stage is described on all four:

| Lens | Question it answers |
|---|---|
| **Object** | What object is created here? What are its fields? |
| **Location** | Where does it live — which process, which store, which row? |
| **Handoff** | Who receives it next, and through what interface? |
| **Mutation** | What is added, overwritten, or discarded? |

---

## 1. TL;DR — the 30-second version

```
Browser ──POST──▶ FastAPI ──INSERT──▶ Postgres ──LPUSH──▶ Redis list
                       │                                   │
                  COMMIT tx1                          RPOP+ZADD (Lua)
                                                           │
                                                     Worker (any replica)
                                                           │
                                          ┌────────────────┴─────────────────┐
                                          │  TX2a: SELECT..FOR UPDATE        │
                                          │  + INSERT session_leases         │
                                          │  + blog_sessions → PROCESSING    │
                                          └────────────────┬─────────────────┘
                                                           │
                                          ┌────────────────┴─────────────────┐
                                          │  ADK Runner over Gemini          │
                                          │  state lives in Redis            │
                                          │  adk:session:<adk_session_id>    │
                                          └────────────────┬─────────────────┘
                                                           │
                                    ┌──────────────────────┴───────────────┐
                                    │                                        │
                          PAUSE (outline HITL)                    COMPLETE (draft)
                                    │                                        │
                          TX2b: pause metadata                 TX2b: costs + versions
                          blog_sessions →                       blog_sessions →
                          AWAITING_OUTLINE_REVIEW               AWAITING_FINAL_REVIEW
                                    │                                        │
                              Human reviews                          Human reviews
                                    │                                        │
                        POST /outline/review                  POST /final-review
                                    │                                        │
                          resume_outline phase                        3 outcomes
```

**The five identifiers you must keep straight.** Everything downstream is keyed off these,
and confusing them is the single most common source of bugs in this codebase:

| # | Identifier | Type | Created at | Scope | Purpose |
|---|---|---|---|---|---|
| 1 | `BlogSession.id` | `int` (PK) | `blog_routes.py:89` → `blog_session_repository.py:35` | DB | The public handle. What the frontend polls. |
| 2 | `BlogSession.adk_session_id` | `uuid4` str | `blog_service.py:64` | DB + Redis key | The ADK conversation identity. Names the Redis session blob. |
| 3 | `BlogJob.phase` | str enum | `blog_service.py:106` | Redis payload | Which pipeline entrypoint to run. **The only mutable trigger.** |
| 4 | `BlogJob.invocation_id` | str | ADK, extracted at `pipeline.py:409` | Redis + DB | ADK's resume handle. `None` on fresh runs. |
| 5 | `confirmation_request_id` | str | ADK tool-call id, `pipeline.py:409` | Redis + DB | The ADK function-call id the user's approval must be bound to. |

> **Rule of thumb:** Redis job payloads are *hints*. Postgres is *truth*. On dequeue the worker
> throws the payload away and re-hydrates from the DB (`session_lease_repository.py:251-264`).
> This is deliberate and is the reason the reaper can repair drift — but it also means a
> `BlogJob` you see in Redis may differ from what actually executes.

---

## 2. Actor map

| Process | Replicas | Entry point | Holds |
|---|---|---|---|
| `api` | 1–N | `src/api/main.py:app` | FastAPI, 1 `AsyncSession` per request |
| `worker` | 2 | `python -m src.workers.blog_worker` | Semaphore(3), 1 `AsyncSession` per phase |
| `reaper` | **exactly 1** | `python -m src.workers.reaper` | Its own sessions; **must not** run in the worker (`blog_worker.py:5-8`) |

Shared infrastructure:

- **PostgreSQL 16** — canonical state. 10 tables (`orm_models.py`).
- **Redis** — four distinct concerns sharing one pool (`core/redis_pool.py`, `max_connections=20`):
  1. `blogify:tasks` — list (job queue)
  2. `blogify:processing` — sorted set (visibility timeout / in-flight)
  3. `adk:session:<adk_session_id>` — agent state, 24h TTL (`session_store.py:32-33`)
  4. `ratelimit:*`, `budget_lock:<user_id>`, `blogify:worker:<id>`
- **Tempo / Prometheus / Grafana** — via OTel auto-instrumentation; no per-agent code.

---

## 3. Phase 0 — Pre-generation (once per user, at registration)

Not part of a blog generation, but the generation **cannot start** without it.

`POST /api/v1/auth/register` → `auth_service.py:44-76`:

| Step | ORM op | Effect |
|---|---|---|
| 1 | `INSERT auth_users` | `password_hash` via `bcrypt` |
| 2 | `BudgetAccountRepository.apply_grant` → `INSERT/UPDATE budget_accounts` | `balance_usd += 5.00`, `total_granted_usd += 5.00` |
| 3 | `BudgetRepository.write_entry` → `INSERT budget_ledger` | `GRANT`, `tokens=+500000`, `amount_usd=+5.00` |

`user_blog_quotas` is **not** created here — it is lazily created by `get_or_create` on the
first `/generate` call (`blog_quota_repository.py:20-30`), defaulting to `blogs_used=0, blogs_limit=10`.

Cookie: an HMAC-SHA256 JWT is set as `httpOnly` cookie `blogify_access_token`
(`local_auth_service.py:143-155`). The frontend never sends an `Authorization` header; it
relies on `credentials: 'include'` (`frontend/src/lib/api/base.ts:59`).

---

## 4. Phase 1 — Ingestion: `POST /api/v1/blogs/generate`

**Process:** `api` · **Transaction:** one, opened by `get_db_session` (`core/database.py:19-24`),
committed by the dependency teardown *after* the handler returns.

### 4.1 Middleware gauntlet (before the handler)

| Order | Middleware | Effect |
|---|---|---|
| 1 | `PrometheusMiddleware` | `main.py:90` — records `http_requests_total` using the **route template**, not the raw path, to keep label cardinality sane (`main.py:47-53`) |
| 2 | `CORSMiddleware` | `main.py:91` |
| 3 | `AuthMiddleware` | `main.py:98` — decodes the cookie into `request.state.user_id` |
| 4 | `RateLimitMiddleware` | `main.py:99` — global + per-IP request rate |
| 5 | `Depends(blog_generation_limit)` | `blog_routes.py:59` → Redis sliding window, `config.rate_limit_blogs_per_day`, 24h window → **429** with `Retry-After` |
| 6 | `Depends(get_db_session)` | opens the transaction |

### 4.2 Validation layer (order matters)

```
GenerateRequest (Pydantic)          schemas.py:145-149   topic 3..500, audience ≤255, tone ∈ Tone enum
  └─ InputGuard.validate            guards/input_guard.py:20-63
       ├─ topic: 3..500, no \x00 \n \r \t
       ├─ audience: ≤255
       └─ tone: coerced lower, must parse as Tone
          └─ failure → HTTPException(400)
```

> ⚠️ **The two length floors disagree.** Pydantic and `InputGuard` both accept a topic as short
> as **3** characters. `sanitize_topic` requires **10** (`sanitization.py:112`). The frontend
> independently enforces 10 client-side (`DashboardPage.tsx:87-90`), which masks the gap for
> browser traffic but not for direct API calls. See Finding **F-01**.

### 4.3 Quota gate — before any budget is touched

`blog_routes.py:77-86`:

```
BlogQuotaRepository.get_remaining(user_id)
  └─ get_or_create  →  INSERT user_blog_quotas (blogs_used=0, blogs_limit=10)   ← FIRST WRITE
remaining = 10 - blogs_used
if remaining <= 0 → HTTP 402 {error_code: QUOTA_EXHAUSTED}
```

### 4.4 `BlogService.create_generation` — the core of ingestion

`blog_service.py:38-111`. Nine steps, all inside **one** transaction:

| # | Code | ORM effect | Redis effect |
|---|---|---|---|
| 1 | `:47-57` | `SELECT blog_sessions WHERE user_id=? AND idempotency_key=?` | — |
| 1a | | ↳ if found & terminal → raise `SessionTerminalError` → **409** | — |
| 1b | | ↳ if found & non-terminal → **return existing row**, no new work | — |
| 2 | `:59-62` | `SELECT COUNT(*) WHERE status IN (QUEUED, PROCESSING, AWAITING_*)` → if ≥1 raise → **409** | — |
| 3 | `:64` | — | — |
| 4 | `:65-72` | **`INSERT blog_sessions`** — `adk_session_id=uuid4()`, `status=QUEUED`, `idempotency_key` | — |
| 5 | `:73-88` | **`INSERT blog_versions`** v1 + `UPDATE blog_sessions SET active_blog_version_id=<v1.id>, job_phase='fresh_generation'` | — |
| 6 | `:90-92` | — | `SET budget_lock:<uid> 1 NX EX 10` |
| 7 | `:94-97` | `UPDATE budget_accounts SET reserved_usd += 1.00`<br>`INSERT budget_ledger` (RESERVE)<br>`INSERT session_reservations`<br>`UPDATE blog_sessions SET budget_reserved_*` | `DEL budget_lock:<uid>` (in `finally`) |
| 8 | `:99-108` | — | **`LPUSH blogify:tasks <json>`** |
| 9 | `:109` | — | `blog_generations_total{status="initiated"}.inc()` |

**The object created in step 4** — `BlogSession` (`orm_models.py:171-218`):

```
id                     ← DB sequence, assigned at flush()
user_id                ← from cookie
topic                  ← verbatim from request
audience               ← verbatim from request
tone                   ← verbatim  ⚠️ NEVER READ BY THE PIPELINE (F-04)
status                 = "QUEUED"
current_stage          = NULL
job_phase              = NULL → set to "fresh_generation" in step 5
active_blog_version_id = NULL → set to v1.id in step 5
adk_session_id         ← uuid4()
invocation_id          = NULL
confirmation_request_id= NULL
outline_data           = NULL
final_content          = NULL
budget_reserved_tokens = 0 → 50000   (step 7)
budget_reserved_usd    = 0 → 1.00000000
budget_spent_tokens    = 0
budget_spent_usd       = 0
reap_count             = 0
idempotency_key        ← header, else body, else NULL
created_at/updated_at  ← _now() (Python-side default, orm_models.py:25-26)
completed_at/failed_at/failure_reason = NULL
```

**The object created in step 5** — `BlogVersion` v1 (`orm_models.py:221-256`):

```
id                  ← sequence
blog_session_id     ← session.id
version_number      = 1
status              ← inherited from blog_session.status = "QUEUED"
job_phase           = "fresh_generation"
title               ← blog_session.topic   (⚠️ the *topic*, not a title; replaced later)
outline_data/approved_outline/research_data = NULL
draft_content/final_content/editor_review/feedback_text = NULL
user_action         = NULL
adk_session_id      ← blog_session.adk_session_id
invocation_id/confirmation_request_id = NULL
state_snapshot      ← the 10-key seed dict (see §6.1)
created_from        = "fresh_generation"
```

`BlogSession.active_blog_version_id` is a **self-referential FK to `blog_versions.id`**
declared on `blog_sessions` (`orm_models.py:182-184`), added by migration `c2d4e6f8a9b1`.
This is a circular FK — `blog_sessions` references `blog_versions` which references
`blog_sessions`. Postgres allows it (deferred at insert time by the ORM's flush ordering),
but it means neither table can be inserted without the other in the same transaction.

### 4.5 What is *added* at ingestion

- a `blog_sessions` row
- a `blog_versions` row
- possibly a `user_blog_quotas` row
- possibly a `budget_accounts` row (`get_or_create` in `apply_reserve`)
- a `budget_ledger` RESERVE row
- a `session_reservations` row
- a Redis list entry

### 4.6 What is *discarded* at ingestion

| Discarded | Where | Consequence |
|---|---|---|
| `tone` | never referenced after `blog_session_repository.py:39` | the whole pipeline is tone-agnostic; stored + echoed, never applied |
| the Redis lock `budget_lock:<uid>` | `blog_service.py:97` | correct — released in `finally` |
| any `Idempotency-Key` on a terminal session | `blog_service.py:51-55` | 409; client must mint a new key |
| — | | |

### 4.7 ⚠️ The queue write precedes the commit

`LPUSH` (`task_queue.py:53`) happens at `:108`, but the Postgres `COMMIT` happens later, in
the `get_db_session` dependency teardown (`database.py:22`). Consequences:

- A worker can `RPOP` the job **before** the row is visible. It then blocks on
  `SELECT … FOR UPDATE` (`session_lease_repository.py:46`) until the API commits. Correct, but
  it is a lock-ordering hazard, not a designed handshake.
- If the `COMMIT` fails, the job is **orphaned in Redis** with no DB row. The worker's
  `acquire_lease` returns `acquired=False` (`session_lease_repository.py:47-48`) and the job
  is acked and dropped. The reaper's `_reconcile_queued_sessions` cannot find it either
  (`blog_session_repository.py:131-155` needs a row). **Silent, correct, unlogged drop.**

---

## 5. Phase 2 — Queue transit

`task_queue.py`. FIFO via `LPUSH` + `RPOP`; in-flight tracking via a sorted set scored by a
visibility deadline.

```
DEQUEUE_SCRIPT (Lua, task_queue.py:34-39) — atomic:
    local job = redis.call('RPOP', KEYS[1])      -- blogify:tasks
    if not job then return nil end
    redis.call('ZADD', KEYS[2], ARGV[1], job)    -- blogify:processing, score = deadline
    return job
```

- `LPUSH` at the head + `RPOP` at the tail = FIFO. ✔
- The Lua script is the only place `RPOP` and `ZADD` happen together — without it there is a
  window where a job is popped but not tracked, and the reaper could double-process it.
- `VISIBILITY_TIMEOUT_SECONDS = 300` (`task_queue.py:32`) — the score written at dequeue.
- Fallback: if `evalsha` fails (script cache miss after Redis restart), it retries with full
  `eval` (`task_queue.py:69-77`).

**Payload shape** — `BlogJob` (`task_queue.py:13-26`):

```
session_id, user_id, adk_session_id, topic, audience, tone, phase,
invocation_id, confirmation_request_id, approved_outline, feedback_text, enqueued_at
```

At `fresh_generation` only the first six + `phase` + `enqueued_at` are populated; the rest are
`None`. Serialised with `json.dumps(job.__dict__)` — note this depends on **field declaration
order** matching between the writer and reader, which holds because both processes import the
same dataclass.

**Worker dequeue loop** — `blog_worker.py:49-54`:

```python
while self._running:
    job = await self._queue.dequeue(timeout=5)
    if job is None:
        await asyncio.sleep(EMPTY_QUEUE_BACKOFF_SECONDS)   # 20s
        continue
    asyncio.create_task(self._process_job(job))            # fire-and-forget task
```

The `timeout=5` argument is **dead** — `dequeue` uses `evalsha`, which is non-blocking, so the
worker actually spins on the 20s backoff whenever the queue is empty. Not a bug, but the
parameter name lies. Concurrency is bounded by `asyncio.Semaphore(3)` (`:43`, `:57`).

---

## 6. Phase 3 — Lease acquisition (the concurrency gate)

`blog_worker.py:56-104` → `session_lease_repository.py:40-100`.

This is the most important transaction in the worker. **TX-1** (`blog_worker.py:59-72`):

### 6.1 Lease acquisition, step by step

| Step | Code | SQL |
|---|---|---|
| 1 | `:46` | `SELECT * FROM blog_sessions WHERE id=? FOR UPDATE` — **row lock held for the whole TX** |
| 2 | `:50-52` | `SELECT … FROM session_leases WHERE blog_session_id=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1`; if held by a *different* worker → `acquired=False` |
| 3 | `:54` | `new_version = current.lease_version + 1` (or 1) |
| 4 | `:55` | `_resolve_active_version` → `SELECT blog_versions WHERE id = blog_session.active_blog_version_id` |
| 5 | `:56` | `_validate_phase_state` — see below |
| 6 | `:58-80` | re-acquire by same owner → `UPDATE session_leases SET lease_expires_at, last_heartbeat_at` |
| 6' | `:82-100` | new owner → **`INSERT session_leases`** (`lease_owner=worker-<host>-<pid>`, `lease_expires_at=now+300`, `release_reason='ACQUIRED'`) |
| 7 | `:72/92` | `_mark_processing` → `UPDATE blog_sessions SET status='PROCESSING', job_phase=<phase>, current_stage=<stage>` **and** `UPDATE blog_versions SET status='PROCESSING', job_phase=<phase>` |
| 8 | `:73/93` | `_hydrate_job` → rebuild a `BlogJob` **from the DB**, discarding the Redis payload |
| 9 | `blog_worker.py:69` | **`COMMIT`** |

`_validate_phase_state` (`:209-235`) — the admission-control rules:

| phase | Requires |
|---|---|
| *all* | `blog_sessions.status == 'QUEUED'` |
| `fresh_generation` | nothing more |
| `resume_outline` | `approved_outline OR outline_data`, **and** `invocation_id`, **and** `confirmation_request_id` |
| `research_phase` | `approved_outline OR outline_data` |
| `revision` | `draft_content OR final_content` |

`current_stage` mapping (`:266-271`): `fresh_generation → "intent"`;
`resume_outline`/`research_phase → "research"`; `revision → "revision_research"`.

### 6.2 Revision forks the version chain here

`_resolve_active_version` (`:187-203`): for `phase == "revision"` it calls
`create_revision_from_active` (`blog_version_repository.py:80-117`), which:

1. computes `version_number = MAX(version_number) + 1` (`:72-78`)
2. **deep-copies** `outline_data`, `approved_outline`, `research_data`, `draft_content`,
   `final_content`, `editor_review`, `state_snapshot` from v1 into v2
3. overwrites `state_snapshot["outline_feedback"]` with the user's feedback (`:89-90`)
4. `INSERT blog_versions` v2, `created_from="revision"`
5. `UPDATE blog_sessions SET active_blog_version_id = v2.id`

So `blog_versions` is a **fork-on-write snapshot chain**, not an append-only log. v1 keeps its
pre-revision content; v2 becomes the active pointer target.

### 6.3 What `_hydrate_job` adds

`session_lease_repository.py:251-264`. This is where the four resume-critical fields enter the
executor — they came from Postgres, not from the Redis payload:

```python
invocation_id          = active_version.invocation_id          # None on fresh runs
confirmation_request_id= active_version.confirmation_request_id
approved_outline       = active_version.approved_outline or active_version.outline_data
feedback_text          = active_version.feedback_text
adk_session_id         = active_version.adk_session_id or session_model.adk_session_id
```

> `approved_outline or outline_data` — on the resume path this prefers the *generated* outline
> when the user has not yet approved one. `_validate_phase_state` accepts either, so a
> `research_phase` recovery can proceed on an unapproved outline.

### 6.4 Heartbeat

`blog_worker.py:106-120`: every 30s, `UPDATE session_leases SET lease_expires_at=now+90,
last_heartbeat_at=now WHERE … AND lease_owner=WORKER_ID`. Note the asymmetry: initial lease
is 300s, heartbeat extends by only **90s**. Any 90s+ stall loses the lease mid-run. Failures
are swallowed (`except Exception: pass`) — deliberate, to avoid killing a healthy job.

---

## 7. Phase 4 — The ADK pipeline run

`executor.py:60-87` dispatches on `job.phase` inside a root OTel span
`pipeline_executor.execute` (`executor.py:69-73`).

**TX-2** opens at `blog_worker.py:84` and stays open for the entire pipeline — **including all
LLM calls** (typically 30–90s). The session is idle during that window; the DB sees nothing
until the first `_commit_costs` write. There is no `READ COMMITTED` blocking (nothing else
touches those rows) but the connection is checked out for the whole duration. With
`pool_size=10, max_overflow=20` (`database.py:10-11`) and `MAX_CONCURRENT_JOBS=3`, this is
not currently a bottleneck.

### 7.1 Agent topology

Built once at import time (`pipeline.py:170-174`):

```python
APP = App(name="blogify",
          root_agent=_build_blog_pipeline(),
          resumability_config=ResumabilityConfig(is_resumable=True))
```

```
SequentialAgent "blog_pipeline"
├── intent_classifier     Gemini 2.5 Flash  temp 0.7  8192 max  retry 3  output_key=intent_result
├── outline_agent         Gemini 2.5 Flash  temp 0.7  8192 max  retry 3  output_key=blog_outline
├── outline_review_agent  Gemini 2.5 Flash  (reuses writer_agent.model)   output_key=outline_review_result
│   └── tool: review_generated_outline
├── research_agent        Gemini 2.5 Flash  temp 0.7  8192 max  retry 3  tool: research_topic (Tavily)
│                                                              output_key=research_data
└── LoopAgent "full_pipeline_draft_refinement_loop"   max_iterations=2
    ├── writer_agent      Gemini 2.5 Flash  temp 0.7  16384 max retry 3  output_key=blog_draft
    └── editor_agent      Gemini 2.5 Flash  temp 0.7  8192 max  retry 3  output_key=editor_review
```

Every agent is `gemini-2.5-flash` (`agent_config.py:21-46`). Retry: 3 attempts,
exponential backoff from 8s, jitter 1.0, on HTTP 429/500/502/503
(`agent_config.py:49-59`).

### 7.2 The state contract — 10 keys

Seeded by `_initial_state` (`pipeline.py:227-239`) and mirrored 1:1 into the Postgres seed
snapshot at `blog_service.py:76-87`:

| Key | Written by | Read by |
|---|---|---|
| `topic` | seed only (never overwritten) | initial message, phase message |
| `audience` | seed only | initial message, phase message |
| `intent_result` | `intent_classifier` | `outline_agent` |
| `blog_outline` | `outline_agent`; then **rewritten** by `review_generated_outline` at `pipeline.py:107` | `outline_review_agent`, `research_agent` |
| `approved_outline` | `review_generated_outline` only, on confirm (`pipeline.py:108`) | never read by an agent |
| `outline_feedback` | `review_generated_outline` (`:109`) | never read by an agent |
| `outline_review_result` | `outline_review_agent` output_key | never read by an agent |
| `research_data` | `research_agent` | `editor_agent` |
| `blog_draft` | `writer_agent` | `editor_agent` |
| `editor_review` | `editor_agent` | `_finalize_result` only |

> Only four keys are actually consumed by another agent's prompt. Six exist purely for
> durability. This is fine — it is the ADK idiom (`output_key` is both the persistence slot
> and the template variable).

### 7.3 `run_pipeline()` — the happy path

`pipeline.py:499-553`, in order:

1. `:509` `sanitize_topic(topic)` → `safe_topic`. **⚠️ the validity flag is discarded**
   (`_, safe_topic, _ =`) — see F-01.
2. `:510` `sanitize_audience(audience)` → injection hit ⇒ hard-coded `"general readers"`;
   >200 chars ⇒ truncated (F-02).
3. `:523-529` `_ensure_session` → if `adk:session:<adk_session_id>` absent,
   `SET adk:session:<id> {…, state: _initial_state(…), events: []} EX 86400`.
4. `:530-535` `_sync_session_state` → if a Postgres `state_snapshot` exists, **overwrite** the
   Redis state with it (`update_session_state`, `session_store.py:312-335`). Redis now mirrors
   Postgres, which is what makes `research_phase` recovery possible after a Redis flush.
5. `:536` `_build_runner(svc)` → `Runner(app=APP, app_name="blogify", session_service=svc)`
6. `:537-542` `_run_runner(new_message=_build_initial_message(...))` → the async generator:

```
"Generate a blog post about: {safe_topic}\nTarget audience: {safe_audience}"
```

   `runner.run_async` yields `Event` objects. **The entire event list is accumulated in
   memory** (`pipeline.py:421`, `:434`) — including every function call, function response,
   and partial LLM chunk. For a 5-agent pipeline this is a few hundred objects; it is never
   streamed to the DB.
7. `:543-549` `_finalize_result`.

### 7.4 The outline HITL pause — `review_generated_outline`

`pipeline.py:70-115`. This is the mechanism the whole "resumable" architecture rests on.

**First pass** (`tool_context.tool_confirmation` is `None`, `:75`):

```python
payload = {"topic": …, "audience": …, "outline": OutlineSchema.model_validate(state["blog_outline"]).model_dump(),
           "instructions": "Review the outline. You can edit…",
           "response_schema": {"approved_outline": "OutlineSchema", "feedback_text": "Optional string"}}
tool_context.request_confirmation(hint=…, payload=payload)
tool_context.actions.skip_summarization = True
return {"status": "awaiting_outline_review", "outline": validated_outline}
```

`OutlineSchema.model_validate` (`schemas.py:31-36`) is the **hard schema gate**: `title ≤120`,
`sections` 3–7, each `target_words` 80–300, `estimated_total_words` 300–2000. A malformed
outline raises *inside the tool*, failing the agent turn.

`skip_summarization = True` prevents the LLM from narrating the pause — it keeps the pause
clean.

**Second pass** (after resume, `:99-115`): reads `tool_confirmation.payload`, re-validates
through `OutlineSchema`, then **overwrites three state keys**:
`blog_outline = approved_outline`, `approved_outline = approved_outline`,
`outline_feedback = feedback_text`.

> This is the subtle bit: `blog_outline` (the *generated* outline) is **overwritten** by the
> approved one. Downstream, `research_agent` reads `{blog_outline}` — so the approved version
> is what gets researched. But it also means the original generated outline is gone from ADK
> state. It survives only in `blog_versions.outline_data`, which
> `blog_service.py:141-142` also overwrites with the approved outline. **The pre-approval
> outline is not recoverable from either store** (F-06).

### 7.5 `_finalize_result` — state → result

`pipeline.py:448-496`:

```python
latest = await svc.get_session(…)                       # re-read Redis
state  = latest.state
_populate_result_from_state(result, state)              # :242-252
result.final_content = editor_review["final_blog"] if editor_review.get("approved") else result.draft
result.costs.extend(_extract_costs_from_events(events))
(paused, invocation_id, confirmation_request_id, payload) = _extract_pause_metadata(events)
```

`_extract_pause_metadata` (`:396-410`) walks events **in reverse** and returns the *last*
function call named `adk_request_confirmation`, pulling `invocation_id` off the event and the
`toolConfirmation.payload` out of `args`.

`_extract_costs_from_events` (`:185-224`) — **token attribution**:

```python
STAGE_BY_AUTHOR = {"intent_classifier": "intent", "outline_agent": "outline",
                   "research_agent": "research", "writer_agent": "writer",
                   "editor_agent": "editor"}
```

Every `Event` with `usage_metadata` is attributed to a stage by its `author` and accumulated
into a `CostInfo`. **Authors not in this map are silently dropped** — and
`outline_review_agent` is not in it. See **F-03**.

### 7.6 `_execute_fresh_generation` returns

`executor.py:89-125`: `await agent_delay()` (a hard-coded `asyncio.sleep(2)`,
`agent_config.py:76-77`) then branch on `result.error` / `result.paused_for_confirmation`.

---

## 8. Phase 5 — Pause persistence (`_handle_outline_pause`)

`executor.py:216-259`, still inside **TX-2**.

| Step | Code | ORM effect |
|---|---|---|
| 1 | `:223` | `_commit_costs(job, result.costs)` — **no `research_data`** passed, so no sources this round |
| 2 | `:225` | `_normalize_research_data(result.research)` — accepts dict *or* JSON string (`:471-482`) |
| 3 | `:227` | `_build_state_snapshot(...)` (`:443-462`) |
| 4 | `:229-245` | `UPDATE blog_versions` v1 → `status='AWAITING_OUTLINE_REVIEW'`, `job_phase='resume_outline'`, `title=_extract_title(outline, topic)`, `outline_data`, `research_data`, `draft_content`, `final_content`, `editor_review`, `invocation_id`, `confirmation_request_id`, `state_snapshot` |
| 5 | `:247-253` | `UPDATE blog_sessions` → `outline_data`, `invocation_id`, `confirmation_request_id`, `adk_session_id` |
| 6 | `:255-259` | `UPDATE blog_sessions` → `status='AWAITING_OUTLINE_REVIEW'`, `current_stage='outline_review'` (**validated** against the state machine) |
| — | | `blog_worker.py:87` **`COMMIT`** |
| 7 | `blog_worker.py:88` | `ZREM blogify:processing <original job json>` — ack **after** commit ✔ |
| 8 | `blog_worker.py:104,122-129` | `UPDATE session_leases SET ended_at=now, release_reason='RELEASED'` — **separate TX** |

`_extract_title` (`:464-469`): `outline["title"].strip()` or fall back to the topic.

### 8.1 `_build_state_snapshot` — the 10-key Postgres mirror

`executor.py:443-462`:

```python
{
  "topic":                job.topic,
  "audience":             job.audience,
  "intent_result":        result.intent_result or {},
  "blog_outline":         result.outline or {},
  "approved_outline":     result.outline or job.approved_outline or {},   # ← prefers generated
  "outline_feedback":     feedback_text or "",
  "outline_review_result":result.confirmation_payload or {},
  "research_data":        normalized_research,
  "blog_draft":           result.draft or "",
  "editor_review":        result.editor_review or {},
}
```

Two observations:

- `approved_outline` is populated with **`result.outline`** first. On the pause path
  `result.outline == state["blog_outline"]` (the generated one), so the snapshot claims the
  generated outline is "approved". On the resume path
  `review_generated_outline` has already overwritten `blog_outline`, so it happens to be the
  approved one. **Correct by coincidence of ordering, not by construction** (F-07).
- `topic`/`audience` come from `job`, i.e. **from Postgres, unsanitized** — while the ADK
  Redis state holds the *sanitized* versions. The snapshot is therefore not a faithful mirror.

### 8.2 The state machine gate

`update_status` (`blog_session_repository.py:157-176`) calls
`BlogSessionStatus.validate_transition` (`orm_models.py:93-107`). The transition table
(`orm_models.py:52-73`):

```
QUEUED                → {PROCESSING, FAILED, CANCELLED}
PROCESSING            → {AWAITING_OUTLINE_REVIEW, AWAITING_FINAL_REVIEW, FAILED, CANCELLED}
AWAITING_OUTLINE_REVIEW → {QUEUED, FAILED, CANCELLED}
AWAITING_FINAL_REVIEW → {COMPLETED, QUEUED, FAILED, REJECTED, CANCELLED}
COMPLETED / FAILED / REJECTED / CANCELLED → {} (terminal)
```

`mark_failed` (`:280-294`) and the reaper's `recover_stale_processing_session` (`:178-208`)
are the only writers that can bypass this — and the latter is explicitly documented as a
separate control path.

---

## 9. Phase 6 — The user's outline review

`POST /api/v1/blogs/{id}/outline/review` (`blog_routes.py:185-223`).

Two routes exist and both call the same service method:
`/outline/review` (frontend, takes `action` + `edited_outline`) and
`/outline-review` (backend-native, takes `approved_outline` directly).

`BlogService.submit_outline_review` (`blog_service.py:124-172`) — **TX-3**:

| Step | Code | Effect |
|---|---|---|
| 1 | `:132-134` | guard: `status == AWAITING_OUTLINE_REVIEW` else **409** |
| 2 | `:136-138` | `SELECT` active version; none → **409** |
| 3 | `:140-143` | build new snapshot: `blog_outline = approved_outline`, `approved_outline = approved_outline`, `outline_feedback = feedback` |
| 4 | `:145-153` | `UPDATE blog_versions` → `status='QUEUED'`, `job_phase='resume_outline'`, `outline_data`, `approved_outline`, `feedback_text`, `state_snapshot` |
| 5 | `:155-159` | **in-Python mutation + `flush()`**: `session.outline_data`, `status='QUEUED'`, `job_phase='resume_outline'` |
| 6 | `:161-170` | construct `BlogJob(phase='resume_outline')` and `LPUSH` — **note: `invocation_id`/`confirmation_request_id`/`approved_outline`/`feedback_text` are NOT set here** |
| — | `database.py:22` | `COMMIT` |

> Step 6 is safe *only because* of `_hydrate_job` (§6.3), which repopulates all four fields
> from the version row the worker just wrote. The Redis payload is genuinely just
> `{session_id, phase}`.

**Frontend constraint that matters:** `OutlineReviewPage.tsx:35-53` blocks submission unless
the title is non-empty, there are 3–7 sections, each section has `id`+`heading`+`goal`,
each `target_words` ∈ [80, 300], and `estimated_total_words` equals the sum. This mirrors
`OutlineSchema` and prevents a 422-shaped round trip.

### 9.1 Resume execution

`executor.py:127-160` → `resume_pipeline` (`pipeline.py:668-734`). Identical to
`run_pipeline` except:

1. `:716-720` the message is a **`FunctionResponse`**, not text:

```python
types.Part(function_response=types.FunctionResponse(
    id=confirmation_request_id,                       # ← binds to the paused tool call
    name="adk_request_confirmation",
    response={"confirmed": True,
              "payload": {"approved_outline": OutlineSchema.model_validate(approved_outline).model_dump(),
                          "feedback_text": feedback_text or ""}}))
```

2. `:717` `invocation_id=invocation_id` is passed to `runner.run_async` — this is what makes ADK
   *resume the same invocation* rather than start a new one.

3. The runner is the **full** `APP` (`blog_pipeline`), not a phase runner — ADK replays the
   completed steps internally and continues from the paused tool.

`_execute_resume_outline` calls `_handle_success` unconditionally (`executor.py:160`) because
a resumed invocation cannot pause again.

---

## 10. Phase 7 — `research_phase` recovery

`_execute_research_phase` (`executor.py:189-214`) is byte-identical to `_execute_revision`
except for the docstring. Both call `run_pipeline_from_phase(phase="research_phase")`.

`_build_phase_runner` (`pipeline.py:319-343`) builds a **completely different `App`**:

```
SequentialAgent "blog_research_phase"
├── research_agent
└── LoopAgent "phase_resume_draft_refinement_loop"  (fresh writer + fresh editor, max 2)
```

This is *not* a resume — it is a **fresh pipeline against restored state**. The Postgres
`state_snapshot` is pushed back into Redis by `_sync_session_state` (`pipeline.py:589-594`),
so `{blog_outline}` and `{research_data}` are populated, and research → write → edit runs
again from scratch.

Who triggers it:

| Trigger | Code |
|---|---|
| Reaper, when a session died with `job_phase='resume_outline'` **and** `current_stage='research'` | `reaper.py:214-225` |
| Reaper reconciliation, using the persisted `job_phase` | `reaper.py:180-184` |
| Human, via `revision_requested` at final review (reuses the same phase runner) | `blog_service.py:221-231` |

The `_recovery_phase_for_session` heuristic exists because ADK's own resume is unreliable
once the process that held the invocation is gone, but the *state* is reliably restorable
from Postgres.

---

## 11. Phase 8 — `_handle_success` and the cost/budget commit

`executor.py:261-340`, **TX-2**. Eleven steps:

| # | Code | Effect |
|---|---|---|
| 1 | `:276-277` | `_commit_costs(job, result.costs, normalized_research)` |
| 1a | `:366-373` | if `research_data["sources"]` → **`INSERT research_sources` × N** |
| 1b | `:375-438` | per `CostInfo` with `total_tokens > 0` (see below) |
| 2 | `:278` | re-read active version |
| 3 | `:280-301` | `UPDATE blog_versions` → `AWAITING_FINAL_REVIEW`, `job_phase=<phase>`, `title`, all content columns, `user_action=NULL`, `state_snapshot` |
| 4 | `:303-313` | if `result.final_content` → `UPDATE blog_sessions` (`outline_data`, `final_content`, `invocation_id`, `confirmation_request_id`, `adk_session_id`) |
| 5 | `:315-317` | `budget_service.release_excess(user_id, session_id)` |
| 6 | `:319-323` | `UPDATE blog_sessions` → `status='AWAITING_FINAL_REVIEW'`, `current_stage='final_review'` |
| 7 | `:326-340` | `UPDATE user_blog_quotas SET blogs_used = blogs_used + 1` — **wrapped in try/except, non-fatal** (`:333`) |

### 11.1 `_commit_costs` internals

`executor.py:363-438`.

```
for cost in costs:                          # ordered intent → outline → research → writer → editor
    if cost.total_tokens <= 0: continue
    existing = run_repo.get_by_session_and_stage(session_id, cost.stage)
    if existing and existing.status == COMPLETED:
        continue                            # ← SKIP. No agent_run update, no ledger COMMIT.
    cost_usd = get_model_cost(cost.model, cost.total_tokens)
    if existing:  UPDATE agent_runs …      # never actually reached in practice (see F-08)
    else:         INSERT agent_runs (status=COMPLETED, latency_ms=NULL, completed_at=NULL)
    prometheus: agent_invocations_total, agent_token_usage, agent_cost_usd
                blog_generation_duration_seconds  ← only if latency_ms is not None
    budget_service.commit_stage(user_id, session_id, agent_run_id, actual_tokens, actual_usd)
```

`get_model_cost` (`budget_config.py:22-25`): `(tokens / 1000) * price_per_1k`. For
`gemini-2.5-flash` that is **$0.00002 per 1k tokens** → 50k tokens = **$0.001**.

### 11.2 `commit_stage`

`budget_service.py:78-114`. Idempotency guard: it reads **every** ledger row for the session
(`budget_repository.py:43-50`) and returns early if a `COMMIT` for that `agent_run_id` already
exists. Then `INSERT budget_ledger (COMMIT, tokens=-actual, amount_usd=-actual)` and
`UPDATE blog_sessions SET budget_spent_tokens += actual, budget_spent_usd += actual`.

> That idempotency read is an O(n) full-table scan by session, executed **once per stage** —
> five scans per generation, each growing. Fine at this scale; worth a composite index on
> `(blog_session_id, entry_type)` if volume grows.

### 11.3 `release_excess`

`budget_service.py:116-170`. Four writes:

1. `SELECT session_reservations WHERE blog_session_id=? AND released_at IS NULL`
2. `actual_usd = abs(SELECT SUM(amount_usd) FROM budget_ledger WHERE entry_type='COMMIT')` — deliberately reads the **ledger**, not the session column, because both live in the same uncommitted TX and the column can read stale (`budget_service.py:118-125`)
3. `budget_accounts`: `reserved_usd -= 1.00`, `balance_usd -= actual`, `total_spent_usd += actual`
4. `session_reservations.released_at = now()`, `INSERT budget_ledger (RELEASE, tokens=actual, amount_usd=actual)`

**This is the terminal budget event for the first generation only.** The reservation is
`WHERE released_at IS NULL`-gated, so any later `_handle_success` finds `None`, logs
`release_excess_no_active_reservation` (`budget_service.py:127-133`) and returns. See **F-05**.

---

## 12. Phase 9 — Final review

`POST /api/v1/blogs/{id}/final-review` → `submit_final_review` (`blog_service.py:174-247`).

`FinalReviewRequest` (`schemas.py:195-206`) enforces: `feedback_text` **required and non-empty**
for `revision_requested`, and **forbidden** for the other two actions.

| action | session | version | queue |
|---|---|---|---|
| `approved` | `status='COMPLETED'`, `completed_at=now`, metric `{status="completed"}` | `status='COMPLETED'`, `user_action='APPROVED'`, `completed_at=now` | — |
| `revision_requested` | `status='QUEUED'`, `job_phase='revision'`, `current_stage='revision_requested'`, `failure_reason=NULL` | `status='QUEUED'`, `job_phase='revision'`, `user_action='REVISION_REQUESTED'`, snapshot `outline_feedback = feedback` | `LPUSH` phase=`revision` + `feedback_text` |
| `rejected` | `status='REJECTED'`, `current_stage='rejected'`, `job_phase=NULL`, `failure_reason='Rejected by user'` | `status='REJECTED'`, `user_action='REJECTED'` | — |

> `failure_reason` is reused as a human-rejection reason on the `rejected` path. The column is
> overloaded; `/detail` and `/status` do not surface it, so it is currently invisible.

### 12.1 Revision execution

`_execute_revision` (`executor.py:162-187`) → `run_pipeline_from_phase("research_phase")`, i.e.
**the exact same code path as crash recovery**. The feedback text reaches the writer only via:

`job.feedback_text` → `state_snapshot["outline_feedback"]` → pushed into Redis by
`_sync_session_state` → …and then **nothing**. No agent instruction references
`{outline_feedback}` (`writer_agent.py` reads nothing at all; `editor_agent.py` reads only
`{blog_draft}` and `{research_data}`). **The user's revision feedback never reaches the LLM.**
See **F-09**. This is the single most consequential functional gap.

---

## 13. The ORM picture

### 13.1 Table inventory — what a single happy-path blog touches

| Table | Rows created | When | Columns written over the lifecycle |
|---|---|---|---|
| `auth_users` | — | (registration) | — |
| `budget_accounts` | 1 (on first use) | registration + reserve | `balance_usd`, `reserved_usd`, `total_granted_usd`, `total_spent_usd` |
| `user_blog_quotas` | 1 (on first use) | first `/generate` | `blogs_used` |
| `blog_sessions` | **1** | `create_generation` | `status`, `current_stage`, `job_phase`, `active_blog_version_id`, `adk_session_id`, `invocation_id`, `confirmation_request_id`, `outline_data`, `final_content`, `budget_reserved_*`, `budget_spent_*`, `reap_count`, `completed_at`, `failed_at`, `failure_reason` |
| `blog_versions` | **1 + R** (R = revisions) | `create_generation`, and once per revision at lease acquisition | `status`, `job_phase`, `title`, `outline_data`, `approved_outline`, `research_data`, `draft_content`, `final_content`, `editor_review`, `feedback_text`, `user_action`, `adk_session_id`, `invocation_id`, `confirmation_request_id`, `state_snapshot`, `completed_at`, `failed_at` |
| `agent_runs` | **≤5** (one per metered stage) | `_commit_costs` | `stage_name`, `status`, `total_tokens`, `cost_usd`, `output_snapshot` |
| `budget_ledger` | 1 + 5 + 1 (+R) | grant, reserve, per-stage commit, release | append-only |
| `session_reservations` | 1 | `check_and_reserve` | `reserved_usd`, `reserved_tokens`, `released_at` |
| `research_sources` | **N × runs** | `_commit_costs` when research present | `url`, `title`, `snippet` |
| `session_leases` | **1 + (worker handoffs)** | lease acquire | `lease_owner`, `lease_expires_at`, `lease_version`, `last_heartbeat_at`, `started_at`, `ended_at`, `release_reason` |

**8 of 10 tables** participate. `agent_runs` and `research_sources` are the only ones that
grow with content rather than with phase count.

### 13.2 Transaction boundaries

| # | Opened at | Scope | Contents |
|---|---|---|---|
| **TX-A** | `database.py:19` (dependency) | one HTTP request | quota row, session, v1, account, ledger RESERVE, reservation, budget columns, LPUSH |
| **TX-1** | `blog_worker.py:59` | lease acquisition | `FOR UPDATE` lock, lease row, `→PROCESSING`, version fork if revision, hydrated job |
| **TX-2** | `blog_worker.py:84` | **entire pipeline + all persistence** | idle 30–90s, then sources, agent_runs, ledger COMMITs, budget columns, version, session, account settle, quota |
| **TX-3** | `database.py:19` | one HTTP request | version `→QUEUED`, session `→QUEUED`, LPUSH |
| **TX-4** | `blog_worker.py:124` | lease release | `ended_at`, `release_reason` |
| **TX-R** | `reaper.py:43/119/167` | one reap cycle | lease expiry, `reap_count`, `PROCESSING→QUEUED`, LPUSH |

Six transactions, four of which span more than one store (Postgres **and** Redis). There is no
distributed transaction, no outbox, no two-phase commit. The design's answer to that is:
**make Postgres authoritative and treat Redis as advisory**, then let the reaper reconcile.

### 13.3 Migration reality

Linear chain, head = `e1f2a3b4c5d6`:

```
b0d04a975349 (base, 8 tables)
  → 367700a374ec  session_reservations.created_at server_default=now()
  → a1b2c3d4e5f6  blog_sessions.job_phase
  → c2d4e6f8a9b1  blog_versions + blog_sessions.active_blog_version_id (circular FK)
  → d4e5f6a7b8c9  blog_versions.user_action
  → e1f2a3b4c5d6  user_blog_quotas
```

`alembic/env.py:14,25` uses `Base.metadata` from `orm_models.py` — so autogenerate **would**
catch drift, but CI only runs `alembic upgrade head` (`.github/workflows/ci.yml:78-123`), never
`alembic check`. Divergences that are live today:

| # | Divergence | Impact |
|---|---|---|
| 1 | `agent_runs.blog_session_id` FK: ORM says `ondelete="CASCADE"`, migration created it with **no** ondelete | deleting a session orphans agent_runs rows |
| 2 | `user_blog_quotas.id` has **no** `autoincrement` in the migration (unlike every other table and the ORM) | Postgres emits `integer PRIMARY KEY` with no sequence; the ORM default supplies the value, so inserts work — but the column is fragile |
| 3 | `user_blog_quotas` has `server_default`s the ORM does not declare | invisible to autogenerate (`compare_server_default` unset) |
| 4 | FK/constraint names differ between ORM and migration (`fk_blog_sessions_active_blog_version_id`) | `alembic check` would emit spurious diffs |
| 5 | `docs/database-schema.md` documents a **completely different schema** (`tenants`, `service_clients`, `end_users`, `budget_policies`, `human_review_events`, `export_jobs`, `user_notifications`, legacy `users`/`blogs`/`cost_records`) — none of which exist | the doc is 100% wrong for the current code |

> The stale `.pyc` files in `backend/alembic/versions/__pycache__/` belong to a pre-squash
> migration chain that included those legacy tables. **Delete them** — they make `ls` output
> misleading and will confuse the next person.

---

## 14. Data lineage — the full field matrix

Legend: **→** passed · **⊘** dropped · **=** written to a store

### 14.1 Request-side fields

| Field | Origin | Validated | Sanitized | Job payload | ADK state | DB columns | Notes |
|---|---|---|---|---|---|---|---|
| `topic` | request | Pydantic 3–500, InputGuard 3–500 + no `\n\r\t\x00` | `sanitize_topic` (**10+**, result flag **discarded**) | yes | `state["topic"]` | `blog_sessions.topic`, `snapshot.topic`, `blog_versions.title` (fallback) | F-01 |
| `audience` | request | ≤255 | `sanitize_audience` (≤200, injection→`"general readers"`) | yes | `state["audience"]` | `blog_sessions.audience`, `snapshot.audience` | F-02 |
| `tone` | request | `Tone` enum | ⊘ | **yes** | ⊘ | `blog_sessions.tone` | **never used by any agent** (F-04) |
| `Idempotency-Key` | header | ≤255 (body) | ⊘ | ⊘ | ⊘ | `blog_sessions.idempotency_key` (unique per user) | drives dedup + 409 |
| cookie → `user_id` | JWT `sub` | HS256, aud/iss/exp | ⊘ | yes | `user_id` (ADK key) | all FKs | |

### 14.2 Agent outputs

| Agent output | ADK key | Postgres column | Also written to | Discarded |
|---|---|---|---|---|
| `intent_classifier` | `intent_result` | ⊘ (**no column**) | `state_snapshot.intent_result` | never read after `outline_agent`; invisible in the API |
| `outline_agent` | `blog_outline` | `blog_versions.outline_data`, `blog_sessions.outline_data` | `snapshot.blog_outline`, `blog_versions.title` | overwritten by approval |
| `review_generated_outline` | `blog_outline`, `approved_outline`, `outline_feedback` | `blog_versions.approved_outline`, `blog_versions.feedback_text` | `snapshot.approved_outline`, `snapshot.outline_feedback` | `approved_outline` / `outline_feedback` never reach an agent prompt |
| `outline_review_result` | ADK output_key | `blog_versions.editor_review`? **no** — `editor_review` only | `snapshot.outline_review_result` | **wiped to `{}` on the first revision** (F-10) |
| `research_agent` | `research_data` | `blog_versions.research_data` | `research_sources` rows (url/title/snippet) | `summary`, `total_sources`, `research_method` not stored separately |
| `writer_agent` | `blog_draft` | `blog_versions.draft_content` | `snapshot.blog_draft` | superseded by `final_content` |
| `editor_agent` | `editor_review` | `blog_versions.editor_review` | `snapshot.editor_review`, → `final_content` | `sources_section` never persisted |
| ADK pause | — | `invocation_id`, `confirmation_request_id` | — | — |
| ADK events | — | ⊘ | — | **entire event list discarded after `_extract_costs_from_events`** |

### 14.3 Cost fields

| Field | Origin | Sink | Discarded |
|---|---|---|---|
| `usage_metadata.prompt_token_count` | each `Event` | `CostInfo.prompt_tokens` → `agent_run.output_snapshot.costs` | not a column |
| `usage_metadata.candidates_token_count` | each `Event` | `CostInfo.completion_tokens` | not a column |
| `usage_metadata.total_token_count` | each `Event` | `agent_runs.total_tokens`, `blog_sessions.budget_spent_tokens`, ledger | — |
| `usage_metadata.model_id` | each `Event` | `CostInfo.model` → `get_model_cost` | not stored on `agent_runs` (no `model_name` column) |
| author `outline_review_agent` | `Event` | ⊘ **dropped** | unmetered (F-03) |
| `CostInfo.research_sources` | never populated | `output_snapshot.costs.research_sources` | always `[]` — dead field |
| `latency_ms` | `existing.started_at` delta | `agent_runs.latency_ms` | always `NULL` (F-08) |

---

## 15. Budget math — worked example

Registration + one full successful generation (assume 60,000 total tokens across stages):

### 15.1 The reservation is 1000× too large

```python
# budget_service.py:47
estimated_usd = Decimal(str(ESTIMATED_TOKENS_PER_BLOG)) * Decimal("0.00002")
#                = 50000 * 0.00002  =  1.00 USD
```

```python
# budget_config.py:24
def get_model_cost(model, tokens): return (tokens / 1000) * price_per_1k
#  50000 tokens → (50000/1000) * 0.00002 → 0.001 USD
```

The reservation multiplies **tokens** by a **per-1k** price. It omits the `/1000`. Result:

| Quantity | Value |
|---|---|
| Reserved per blog | **$1.00000000** |
| Actual cost of a 50k-token blog | **$0.00100000** |
| Ratio | **1000×** |
| Initial grant | $5.00 |
| Blogs a user can start | **5** (not the 10 the quota advertises) |
| Balance left after 5 successful blogs | $5.00 − $0.005 ≈ **$4.995**, yet no further blog can start |

**This is the single highest-impact defect in the system.** The reservation is *released* on
success, so `balance_usd` recovers — but `reserved_usd` only drops by what `release_excess`
computes, and `available = balance − reserved`. After `release_excess`,
`reserved_usd → 0`, so the user *can* start another blog. The clamp bites only while a
reservation is outstanding. Still: **a user mid-generation holds $1.00 of a $5.00 balance
(20%) to guard a $0.001 risk**, and any leaked reservation permanently removes 20% of their
budget. See **F-11**.

### 15.2 Ledger walkthrough

| Step | `entry_type` | `tokens` | `amount_usd` | Account effect |
|---|---|---|---|---|
| register | `GRANT` | `+500000` | `+5.00` | `balance 0→5.00`, `granted 0→5.00` |
| generate | `RESERVE` | `−50000` | `−1.00` | `reserved 0→1.00` |
| 5 stage commits | `COMMIT` ×5 | sum `−60000` | sum `−0.0012` | `blog_sessions.budget_spent_*` accumulates |
| release_excess | `RELEASE` | `+60000` | `+0.0012` | `reserved 1.00→0`, `balance 5.00→4.9988`, `spent 0→0.0012` |

> **The ledger does not sum to the balance movement.** `sum(ledger) = −1.00`, but the actual
> balance delta is `−0.0012`. The `RELEASE` row should carry `reserved − actual = +0.9988`,
> not `actual`. The service comment (`budget_service.py:22-23`) explicitly disclaims using the
> ledger for balances, so nothing breaks — but the audit trail is misleading for anyone
> reconciling by hand. See **F-12**.

### 15.3 The frontend token balance is saturated

`blog_routes.py:240-244`:

```python
price_per_token = MODEL_PRICING["gemini-2.5-flash"] / 1000     # 2e-8
total_granted_tokens = 5.00 / 2e-8  = 250,000,000
balance_tokens = max(0, min(MAX_TOKENS_PER_USER=4_000_000, 250_000_000 − spent))
```

The cap is always hit. The dashboard always displays **4,000,000 tokens**, regardless of spend.
Separately, `BudgetPage.tsx:19-20` hard-codes a **1,000,000** capacity — a third disagreeing
number. See **F-13**.

---

## 16. Failure & recovery matrix

| Failure | Detected by | DB effect | Queue effect | Recovery |
|---|---|---|---|---|
| Input invalid | `InputGuard` | none | none | 400 to client |
| Quota exhausted | `blog_routes.py:78` | `user_blog_quotas` read | none | 402 `QUOTA_EXHAUSTED` |
| Daily rate limit | `blog_generation_limit` dep | none | none | 429 + `Retry-After` |
| One active session | `blog_service.py:59-62` | none (rolled back) | none | 409 |
| Idempotency → terminal | `blog_service.py:51-55` | none | none | 409 `SESSION_TERMINAL` |
| Insufficient balance | `budget_account_repository.py:58-62` | rollback of session+version | none | 402 |
| Redis lock contended | `blog_service.py:91-92` | rollback | none | 409 `"Rate limit exceeded"` |
| TX-A commit fails | Postgres | rolled back | **job orphaned** | worker acks & drops (silent) |
| Lease held by other worker | `session_lease_repository.py:51-52` | none | ack + drop | other worker proceeds |
| Session not `QUEUED` | `_validate_phase_state:210-213` | none | ack + drop | **raises** out of TX-1 |
| Missing resume metadata | `_validate_phase_state:218-228` | none | ack + drop | raises; needs reaper |
| Revision w/o draft | `_validate_phase_state:230-233` | none | ack + drop | raises |
| **Agent/API error** | `run_pipeline` catch `:550` | `PipelineResult.error` | — | `_handle_failure` |
| **Any executor exception** | `execute()` catch `:85` | `span.record_exception` | — | `_handle_failure` |
| Worker process dies | lease `ended_at IS NULL` + expiry | `status` stays `PROCESSING` | entry stale in ZSET | reaper, ≤60s cycle |
| Lease heartbeat lost | `get_stale_sessions:142-155` | `PROCESSING→QUEUED`, `reap_count+1` | re-enqueued with derived phase | reaper |
| `reap_count > 3` | `reaper.py:68-77` | `status='FAILED'` | dropped | terminal |
| DB row `QUEUED`, no lease, no Redis entry | `_reconcile_queued_sessions` | none | re-enqueued | reaper |
| Redis processing entry stale, session not `QUEUED` | `_reap_queue:142-159` | none | `ZREM` only (clean) | reaper |
| Redis job malformed | `_decode_job_payload` → `{}` | none | `ZREM` | reaper |

### 16.1 Reaper cycle

`reaper.py:32-40`, every 60s, exactly one replica:

1. **`_reap_stale_leases`** (`:42-112`) — find leases with `ended_at IS NULL`,
   `lease_expires_at < now − 2min`, joined to a `PROCESSING` session. Dedupe by session.
   `mark_expired` → `increment_reap_count` → if `> 3` `mark_failed`, else
   `recover_stale_processing_session` (`PROCESSING→QUEUED`, bypassing the state machine by
   design) → derive phase via `_recovery_phase_for_session` → `LPUSH`.
2. **`_reap_queue`** (`:114-164`) — reclaim `blogify:processing` entries past their deadline.
   Re-enqueue only if `status == QUEUED` **and** `current_stage != 'requeued_by_reaper'` **and**
   no active lease; otherwise just clean.
3. **`_reconcile_queued_sessions`** (`:166-212`) — `SELECT … WHERE status='QUEUED' AND
   updated_at < now − 30s AND NOT EXISTS(open lease)`; anything not in the Redis queue gets
   re-enqueued. This is the safety net that makes the whole design durable.

> `recover_stale_processing_session` sets `current_stage = "requeued_by_reaper"`
> (`:182`). Step 2 checks that exact string to avoid a requeue loop between steps 1 and 3.
> It is a magic string with no enum behind it.

---

## 17. What gets added, mutated, and discarded — summary

### Added along the way

| Added | Where |
|---|---|
| `adk_session_id` (uuid4) | `blog_service.py:64` |
| `BlogVersion` v1 | `blog_service.py:73` |
| budget reservation ($1.00) | `budget_service.py:51-70` |
| 10-key state seed in Redis | `pipeline.py:307` |
| 10-key snapshot in Postgres | `blog_service.py:76-87` |
| `session_leases` row | `session_lease_repository.py:82-90` |
| `research_sources` rows | `executor.py:370-373` |
| `agent_runs` rows | `executor.py:402-409` |
| `budget_ledger` COMMIT rows | `budget_service.py:100-108` |
| `invocation_id` + `confirmation_request_id` | `pipeline.py:409` |
| `BlogVersion` v(n+1) per revision | `blog_version_repository.py:92-110` |
| a **new** ADK state on `research_phase` resume | `session_store.py:79` |
| 2s artificial delay | `agent_config.py:77` |

### Mutated in place

| Mutated | Who |
|---|---|
| `blog_sessions.status` (7 transitions) | worker + API, all via `validate_transition` |
| `blog_sessions.job_phase` | lease acquire, pause, revision |
| `blog_sessions.current_stage` | lease acquire, pause, success, reviews |
| `blog_sessions.active_blog_version_id` | initial version, each revision |
| `blog_sessions.budget_reserved_*` / `budget_spent_*` | reserve, per-stage commit |
| `blog_sessions.reap_count` | reaper only |
| `blog_versions.*` (16 columns) | pause, success, review, failure |
| `budget_accounts.*` (4 columns) | grant, reserve, commit, release |
| `session_leases.lease_expires_at` / `last_heartbeat_at` | heartbeat every 30s |
| Redis `state["blog_outline"]` | `review_generated_outline` |
| Redis `state["approved_outline"]`, `["outline_feedback"]` | `review_generated_outline` |
| Redis `state["events"]` | every `append_event` (grows unbounded within 24h TTL) |

### Discarded (never persisted, never read, or lost)

| Discarded | Where | Severity |
|---|---|---|
| `outline_review_result` / approval decision | wiped to `{}` on first revision (`executor.py:458`) | **high** |
| the pre-approval (generated) outline | overwritten in both ADK state and `outline_data` | **high** |
| the user's revision feedback, from the LLM's perspective | stored but never referenced in any instruction | **high** |
| `outline_review_agent` token usage | `STAGE_BY_AUTHOR` has no entry (`pipeline.py:176-182`) | **high** |
| all revision spend | `_commit_costs` skips `COMPLETED` stages (`executor.py:380-381`) | **high** |
| account `reserved_usd` on revision | `release_excess` finds no open reservation | **high** |
| full ADK event stream | dropped after cost extraction | medium |
| `agent_run.completed_at`, `latency_ms` | never set on the create path | medium |
| `editor_review.sources_section` | not persisted | medium |
| `intent_result` | no dedicated column; only inside `state_snapshot` | medium |
| `tone` | never reaches an agent | medium |
| `CostInfo.research_sources` | always `[]` | low |
| topic validity flag from `sanitize_topic` | `pipeline.py:509` | medium |
| `daily_cost_usd`, `judge_*`, `validation_failures_total`, `service_client_*` metrics | declared in `metrics.py`, **zero call sites** | low |
| `OutputGuard` | `guards/output_guard.py` — **never called anywhere** | medium |

---

## 18. Findings, ranked

### Critical

| ID | Finding | Evidence |
|---|---|---|
| **F-11** | Budget reservation is **1000× the real cost** (missing `/1000`), so a 50k-token blog reserves $1.00 to guard a $0.001 risk. Users hold 20% of their balance per in-flight job; leaked reservations permanently reduce their balance. | `budget_service.py:47` vs `budget_config.py:24` |
| **F-05** | **Revisions are entirely unbilled.** `_commit_costs` skips any stage already `COMPLETED` for the session, and no second reservation is ever created — so on a revision, research+writer+editor tokens are spent, never written to `agent_runs`, never written to `budget_ledger`, and never deducted from `budget_accounts`. | `executor.py:380-381`, `blog_service.py:95` |
| **F-09** | **Revision feedback never reaches the LLM.** `outline_feedback` is persisted into `state_snapshot` but no agent instruction interpolates `{outline_feedback}`. The user's "add more data on X" request is silently dropped. | `blog_service.py:143`, `executor.py:457`, `writer_agent.py`, `editor_agent.py` |
| **F-03** | `outline_review_agent` tokens are **unmetered** — absent from `STAGE_BY_AUTHOR`. | `pipeline.py:176-182` |

### High

| ID | Finding | Evidence |
|---|---|---|
| **F-14** | If `_handle_failure` itself raises (e.g. `mark_failed` on a non-`PROCESSING` session), TX-2 rolls back and the session is **stuck in `PROCESSING` forever** — the reaper's queries require either an *open* lease (there is none; it was released) or `status='QUEUED'`. | `blog_worker.py:95-104`, `reaper.py:142-155`, `blog_session_repository.py:131-155` |
| **F-15** | An **abandoned outline review leaks the reservation permanently.** `_handle_outline_pause` does not settle budget, and no path releases the reservation when the session sits in `AWAITING_OUTLINE_REVIEW` or is later `REJECTED`. `reserved_usd` stays at $1.00 forever. | `executor.py:216-259`, `blog_service.py:232-244` |
| **F-16** | The `RELEASE` ledger row records `actual_usd` instead of `reserved − actual`, so `sum(budget_ledger) ≠ balance delta`. | `budget_service.py:153-161` |
| **F-17** | Lease TTL (300s initial) vs heartbeat extension (90s) mismatch — any >90s stall (a slow Tavily deep-research poll can take 120s: `tavily_research.py:118`) loses the lease mid-run while the worker keeps writing. | `blog_worker.py:36-37,113` |
| **F-18** | `user_blog_quotas.id` has no `autoincrement` in the migration. | `e1f2a3b4c5d6_add_blog_quota_table.py` |

### Medium

| ID | Finding | Evidence |
|---|---|---|
| **F-01** | `sanitize_topic` requires 10 chars and returns `(False, "", msg)`; `pipeline.py:509` discards the flag, so a 3–9 char topic becomes `""` and the LLM is asked to write about nothing. | `pipeline.py:509`, `sanitization.py:112` |
| **F-02** | `sanitize_audience` truncates at 200 chars although the DB column is 255 — and silently substitutes `"general readers"` on an injection hit, with no user-visible signal. | `sanitization.py:157-172` |
| **F-06** | The pre-approval outline is unrecoverable — overwritten in ADK state *and* in `blog_versions.outline_data`. | `pipeline.py:107`, `blog_service.py:141-142` |
| **F-07** | `state_snapshot["approved_outline"]` prefers `result.outline` over the actually-approved outline. Correct only because `review_generated_outline` mutates `blog_outline` first. | `executor.py:456` |
| **F-08** | `agent_runs.latency_ms` and `completed_at` are never set on the create path, and the update path is unreachable (the `COMPLETED` skip fires first). So `blog_generation_duration_seconds` is **never observed**, and every `agent_runs` row has `NULL` latency and completion. | `executor.py:386-399,401-410,417-420` |
| **F-10** | `outline_review_result` (the HITL decision record) is overwritten with `{}` on the first revision. | `executor.py:458`, `:300` |
| **F-19** | Research sources are **never deduplicated** — every re-research (recovery or revision) inserts N more rows, inflating `sources_count` shown in the UI. | `executor.py:366-373` |
| **F-20** | `OutputGuard` (`MIN_WORD_COUNT = 300`, title ≤120) is defined and exported but has **no call sites**. No output-side validation ever runs. | `guards/output_guard.py` |
| **F-21** | `get_by_session_and_stage` uses `scalar_one_or_none()` with no unique constraint on `(blog_session_id, stage_name)`. Safe today only because the `COMPLETED` skip prevents duplicate rows. One code change away from `MultipleResultsFound`. | `agent_run_repository.py:63-70` |
| **F-22** | The frontend's `409 SESSION_TERMINAL` and `402 QUOTA_EXHAUSTED` branches test `err.body.error_code`, but `ApiError` exposes `errorCode` and has no `body`. **Both branches are dead**; users see a generic toast. | `DashboardPage.tsx:127-138` vs `base.ts:8-30` |
| **F-23** | `blog_sessions.active_blog_version_id` is a circular FK and is **unindexed**. Every `get_active_for_session` (`blog_version_repository.py:53-61`) joins on it. | `orm_models.py:182-184` |
| **F-24** | `docs/database-schema.md` documents ~20 tables, 10 of which no longer exist. | `docs/database-schema.md` |

### Low

| ID | Finding | Evidence |
|---|---|---|
| **F-04** | `tone` is stored and echoed but never influences generation. | whole pipeline |
| **F-13** | Dashboard token balance is always the 4M cap; `BudgetPage` uses a separate hard-coded 1M. | `blog_routes.py:244`, `BudgetPage.tsx:19` |
| **F-25** | `dequeue(timeout=5)` param is unused; the loop actually backs off 20s. | `task_queue.py:56`, `blog_worker.py:52` |
| **F-26** | 4 metrics families are declared with **zero** call sites (`daily_cost_usd`, `judge_*`, `validation_failures_total`, `service_client_*`). | `metrics.py:89-113` |
| **F-27** | `failure_reason` is overloaded to carry human-rejection reasons and is surfaced nowhere. | `blog_service.py:236` |
| **F-28** | 6 dead enum values / magic strings: `"requeued_by_reaper"`, `revision_research`, `"redacted"` sentinel, `LeaseEventType.EXPIRED`/`REAPED` (never written), `AgentRunStatus.STARTED`/`FAILED` (never written). | multiple |
| **F-29** | `agent_delay()` = `asyncio.sleep(2)` runs after *every* phase — 8s of pure sleep per blog. | `agent_config.py:76` |
| **F-30** | Stale `.pyc` files in `alembic/versions/__pycache__/` reference a deleted migration chain. | `backend/alembic/versions/__pycache__/` |

---

## 19. If you only read one thing

The architecture is **sound and unusually well-reasoned for its size**: Postgres is
authoritative, Redis is advisory, the reaper reconciles, leases are append-only audit trails,
`_hydrate_job` means a corrupt queue payload cannot corrupt execution, and the state machine is
enforced at the repository layer rather than by convention.

The weakness is not the design — it is that **nothing verifies the design actually ran**.
`backend/tests/` contains 4 files. There is no test for the budget arithmetic, the state
machine, the reservation/release lifecycle, `_commit_costs` idempotency, or any phase
transition. Every finding in §18 with severity High or Critical lives in code that no test
touches.

Suggested order of work:

1. **F-11** — one-line fix (`/ 1000`), immediately restores 10 blogs/user and removes the leak class.
2. **F-09** — add `{outline_feedback}` to the writer's instruction. One line; makes revision actually work.
3. **F-05 + F-03** — key `agent_runs` on `(blog_session_id, stage_name, version)` and record a
   fresh `CostInfo` per invocation instead of per session; add `outline_review_agent` to
   `STAGE_BY_AUTHOR`.
4. **F-14 + F-15** — settle the reservation on the pause path and on rejection; add a reaper
   sweep for `AWAITING_*` sessions with open reservations older than N hours.
5. **F-01** — honour the `sanitize_topic` validity flag.
6. Then write the tests that would have caught all of the above.

---

## 20. Where to look next

| Question | File |
|---|---|
| "what can I legally do at each stage?" | `orm_models.py:39-107` (the state machine) |
| "what SQL does this operation actually run?" | `models/repositories/*.py` — every method is one `select()` |
| "why did my job run the wrong pipeline?" | `session_lease_repository.py:209-235` |
| "where did the tokens go?" | `pipeline.py:185-224` → `executor.py:363-438` |
| "where did the money go?" | `budget_service.py` + `budget_account_repository.py` |
| "why is this session stuck?" | `reaper.py` + `blog_session_repository.py:131-155,178-208` |
| "what does the LLM actually see?" | `agents/*.py` instructions + `state` keys they interpolate |
| "what is the API contract?" | `models/schemas.py` (agent I/O) + `blog_routes.py` (HTTP) |