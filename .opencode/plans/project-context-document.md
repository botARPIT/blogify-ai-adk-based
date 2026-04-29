# Blogify AI ADK — Comprehensive Project Context Document

**Version:** 1.0  
**Date:** 2026-04-01  
**Purpose:** Provide an AI agent with complete context about the Blogify AI ADK application, its database schema, architecture, known issues, and the concurrency fix applied.

---

## 1. What This Application Does

Blogify AI is a **session-based AI blog generation system** that produces blog posts through a multi-stage AI pipeline with human-in-the-loop (HITL) review gates. A user submits a topic and audience, and the system generates a complete blog post through these stages:

1. **Intent Classification** — Clarifies the topic
2. **Outline Generation** — Creates structured outline
3. **Outline Review Gate** — Pauses for human approval of the outline
4. **Research** — Web search via Tavily API
5. **Writer** — Generates draft content
6. **Editor** — Reviews and refines the draft

The system supports two operational modes:
- **Standalone mode** — End users interact directly via `/api/v1/` routes with cookie auth
- **AI Service mode** — An upstream backend calls `/internal/ai/` routes with API key auth

The system enforces strict budget controls: daily USD limits, daily token limits, daily blog count limits, per-session cost limits, and concurrent session limits. Budget enforcement happens at admission time (before the pipeline runs) and at finalization time (after the pipeline completes).

---

## 2. Technology Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI (Python 3.11) |
| ORM | SQLAlchemy 2.x (async) |
| Database | PostgreSQL (via asyncpg) |
| Cache/Queue | Redis |
| AI Framework | Google ADK (Agent Development Kit) with Gemini models |
| Web Search | Tavily API |
| Metrics | Prometheus |
| Observability | OpenTelemetry |
| Auth | Cookie-based (standalone), API key (service mode) |
| Background Processing | Custom Redis-backed task queue |

**Runtime Topology:** API process + Background Worker process + PostgreSQL + Redis

---

## 3. Database Schema — Complete Table Catalog

### 3.1 Multi-Tenant Hierarchy

The schema follows a four-level tenant hierarchy:

```
ServiceClient → Tenant → EndUser → BlogSession
```

- **ServiceClient** — External API consumer (has API key, hashed via SHA-256)
- **Tenant** — Organization within a service client (has plan tier: free/pro/enterprise)
- **EndUser** — Individual user within a tenant (has external_user_id from upstream)
- **BlogSession** — A single blog generation request and its full lifecycle

### 3.2 Core Tables

#### `service_clients`
External API consumers with their own API keys and modes.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `client_key` | String(128), UNIQUE | Identifies the service client |
| `mode` | enum: standalone, blogify_service | |
| `name` | String(255) | |
| `hashed_api_key` | String(255) | SHA-256 of raw API key |
| `status` | enum: active, suspended, rotated | |

#### `tenants`
Organizations within a service client.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `service_client_id` | BigInteger FK → service_clients | |
| `external_tenant_id` | String(255), nullable | From upstream |
| `name` | String(255) | |
| `plan_tier` | enum: free, pro, enterprise | |
| `status` | enum: active, suspended, cancelled | |

#### `end_users`
Individual users within a tenant.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants | |
| `external_user_id` | String(255) | From upstream |
| `email` | String(255), nullable | |
| `status` | enum: active, suspended | |

**UNIQUE constraint:** (tenant_id, external_user_id)

#### `auth_users`
Standalone-mode authenticated users (cookie auth).

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `email` | String(255), UNIQUE | |
| `password_hash` | String(512) | |
| `is_active` | Boolean | |

### 3.3 Blog Generation Tables

#### `blog_sessions`
The central record for a blog generation request and its full lifecycle.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants | |
| `end_user_id` | BigInteger FK → end_users | |
| `service_client_id` | BigInteger FK → service_clients | |
| `external_request_id` | String(255), nullable, indexed | For upstream idempotency |
| `topic` | String(500) | |
| `audience` | String(255), nullable | |
| `tone` | String(100), nullable | |
| `status` | enum, indexed | See state machine below |
| `current_stage` | String(80), nullable | |
| `iteration_count` | Integer | |
| `outline_data` | JSONB, nullable | Stored outline |
| `budget_reserved_usd` | Float | |
| `budget_reserved_tokens` | Integer | |
| `budget_spent_usd` | Float | |
| `budget_spent_tokens` | Integer | |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |
| `completed_at` | DateTime, nullable | |

**Session Status State Machine:**
```
AWAITING_BUDGET_RESOLUTION → (admitted) → QUEUED
QUEUED → PROCESSING
PROCESSING → AWAITING_OUTLINE_REVIEW → (resume) → PROCESSING
PROCESSING → AWAITING_HUMAN_REVIEW → COMPLETED / FAILED / REVISION_REQUESTED
REVISION_REQUESTED → QUEUED → PROCESSING (repeat)
Any → FAILED / CANCELLED / BUDGET_EXHAUSTED
```

**Key invariant:** `AWAITING_BUDGET_RESOLUTION` is a **pre-admission state**. The session is not counted as active. It only transitions to `QUEUED` (active) after budget validation passes.

#### `blog_versions`
Immutable snapshots of blog content at each stage.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `blog_session_id` | BigInteger FK → blog_sessions | |
| `version_number` | Integer | Auto-incremented per session |
| `source_type` | enum: initial_generation, human_revision, chat_edit, manual_import | |
| `title` | String(500), nullable | |
| `content_markdown` | Text, nullable | |
| `word_count` | Integer | |
| `editor_status` | enum: draft, editor_approved, human_approved, human_rejected | |
| `created_by` | enum: system, human, chatbot | |

#### `agent_runs`
Audit trail for each AI agent invocation with cost tracking.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `blog_session_id` | BigInteger FK → blog_sessions | |
| `blog_version_id` | BigInteger FK → blog_versions, nullable | |
| `stage_name` | String(80) | |
| `agent_name` | String(100) | |
| `model_name` | String(100) | |
| `status` | enum: started, completed, failed, timed_out, cancelled | |
| `prompt_tokens` | Integer | |
| `completion_tokens` | Integer | |
| `cost_usd` | Float | |
| `latency_ms` | Integer, nullable | |

#### `human_review_events`
Records of human approval/rejection decisions.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `blog_session_id` | BigInteger FK → blog_sessions | |
| `blog_version_id` | BigInteger FK → blog_versions | |
| `reviewer_user_id` | String(255) | |
| `action` | enum: approve, request_revision, reject, reopen | |
| `feedback_text` | Text, nullable | |

#### `export_jobs`
Export requests (PDF, DOCX, Markdown).

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `blog_version_id` | BigInteger FK → blog_versions | |
| `format` | enum: pdf, docx, markdown | |
| `status` | enum: pending, processing, completed, failed | |
| `artifact_uri` | String(1000), nullable | |

#### `user_notifications`
In-app notifications for auth_users.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `user_id` | BigInteger FK → auth_users | |
| `type` | String(80), indexed | |
| `title` | String(255) | |
| `message` | Text | |
| `session_id` | BigInteger FK → blog_sessions, nullable | |
| `is_read` | Boolean, indexed | |

### 3.4 Budget Tables

#### `budget_policies`
Configurable per-user, per-tenant, or default budget limits.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants, nullable | NULL for default scope |
| `end_user_id` | BigInteger FK → end_users, nullable | NULL for default/tenant scope |
| `scope` | enum: default, tenant, user_override | |
| `daily_cost_limit_usd` | Float, default 1.0 | |
| `daily_token_limit` | Integer, default 50,000 | |
| `daily_blog_limit` | Integer, default 5 | |
| `per_session_cost_limit_usd` | Float, default 0.10 | |
| `per_session_token_limit` | Integer, default 15,000 | |
| `max_revision_iterations_per_session` | Integer, default 3 | |
| `max_concurrent_sessions` | Integer, default 2 | |
| `soft_stop_enabled` | Boolean, default False | |

**Policy resolution hierarchy:** user_override → tenant → default

#### `user_budget_states`
Mutable daily budget state with row-level locking for atomic reserve checks.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants | |
| `end_user_id` | BigInteger FK → end_users | |
| `window_type` | enum, default daily | |
| `window_start` | DateTime | UTC midnight of the window |
| `policy_id` | BigInteger FK → budget_policies, nullable | |
| `daily_limit_usd` | Float | Denormalized from policy |
| `daily_limit_tokens` | Integer | |
| `daily_blog_limit` | Integer | |
| `max_concurrent_sessions` | Integer | |
| `reserved_usd` | Float | Running total of active reservations |
| `reserved_tokens` | Integer | |
| `reserved_blog_count` | Integer | |
| `committed_usd` | Float | Running total of committed spend |
| `committed_tokens` | Integer | |
| `committed_blog_count` | Integer | |
| `active_session_count` | Integer | Cached count (reservation table is truth) |
| `warning_emitted_80_pct` | Boolean | |
| `warning_emitted_100_pct` | Boolean | |

**UNIQUE constraint:** (tenant_id, end_user_id, window_type, window_start)

#### `budget_reservations`
Explicit session-scoped reservation lifecycle for crash-safe accounting.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants | |
| `end_user_id` | BigInteger FK → end_users | |
| `blog_session_id` | BigInteger FK → blog_sessions, indexed | |
| `reservation_scope` | enum: session_initial, session_revision | |
| `iteration_number` | Integer | |
| `status` | enum: active, committed, released, expired, reconciled, indexed | |
| `reserved_usd` | Float | |
| `reserved_tokens` | Integer | |
| `reserved_blog_count` | Integer | |
| `committed_usd` | Float | Running total of committed spend |
| `committed_tokens` | Integer | |
| `released_usd` | Float | Released back to budget pool |
| `released_tokens` | Integer | |
| `lease_expires_at` | DateTime, nullable | For crash-safe reclaim (default 15 min) |
| `released_reason` | String(255), nullable | |

**UNIQUE constraint:** (blog_session_id, reservation_scope, iteration_number, status)

**Reservation Lifecycle:**
```
ACTIVE → COMMITTED (successful pipeline finalize)
ACTIVE → RELEASED (failure, manual release)
ACTIVE → EXPIRED (budget exhaustion mid-pipeline)
ACTIVE → RECONCILED (background reconciliation of timed-out)
```

#### `budget_ledger_entries`
Immutable append-only usage journal for audit and accounting.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `tenant_id` | BigInteger FK → tenants | |
| `end_user_id` | BigInteger FK → end_users | |
| `blog_session_id` | BigInteger FK → blog_sessions, nullable | |
| `blog_version_id` | BigInteger FK → blog_versions, nullable | |
| `agent_run_id` | BigInteger FK → agent_runs, nullable | |
| `reservation_id` | BigInteger FK → budget_reservations, nullable | |
| `entry_type` | enum: reserve, commit, release, adjustment, refund, reject | |
| `resource_type` | enum: tokens, usd, blog_count, revision_count | |
| `window_type` | enum: daily | |
| `window_start` | DateTime, nullable | |
| `quantity` | Float | Positive for reserve/commit, negative for release |
| `unit_cost_usd` | Float, nullable | |
| `metadata` | JSONB, nullable | |
| `created_at` | DateTime | |

#### `service_client_budget_policies`
Per-service-client daily budget limit.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `service_client_id` | BigInteger FK → service_clients, UNIQUE | |
| `daily_budget_limit_usd` | Float | |
| `is_active` | Boolean, default True | |

#### `service_client_budget_states`
Service-client daily budget state (separate from per-user state).

| Field | Type | Notes |
|-------|------|-------|
| `id` | BigInteger PK | |
| `service_client_id` | BigInteger FK → service_clients | |
| `window_type` | enum: daily | |
| `window_start` | DateTime | |
| `daily_limit_usd` | Float | |
| `reserved_usd` | Float | |
| `committed_usd` | Float | |

**UNIQUE constraint:** (service_client_id, window_type, window_start)

### 3.5 Legacy Tables (Read-Only, Not Used by Canonical System)

#### `users` — Legacy user table (deprecated)
#### `blogs` — Legacy blog table (deprecated)
#### `cost_records` — Legacy cost tracking (deprecated)

These tables exist from an earlier version and are NOT used by the canonical budget/session system.

---

## 4. Application Architecture

### 4.1 Request Flow

```
Client → FastAPI → Idempotency Check → Auth → Rate Limit
         → Budget Preflight → Create Session (pre-admission)
         → Budget Admission → Enqueue to Redis Queue
         → Return 202 Accepted

Worker → Dequeue → Run ADK Pipeline → Finalize Budget → Update Session
```

### 4.2 Pipeline Architecture

The blog generation pipeline uses Google ADK's `SequentialAgent` with resumability:

```
SequentialAgent("blog_pipeline", [
    intent_agent,          # Classifies topic clarity
    outline_agent,         # Generates structured outline
    outline_review_agent,  # Pauses for human approval (HITL gate)
    research_agent,        # Web research via Tavily
    LoopAgent("refinement_loop", max_iterations=2, [
        writer_agent,      # Generates draft
        editor_agent,      # Reviews and refines
    ])
])
```

The outline review gate uses ADK's `ResumabilityConfig(is_resumable=True)` to pause execution. When the pipeline pauses, the worker stores the outline and returns. The pipeline resumes when the user approves the outline.

### 4.3 Worker System

**File:** `backend/src/workers/blog_worker.py`

- Polls Redis queue every 1 second
- MAX_CONCURRENT_JOBS = 3 (via asyncio.Semaphore)
- Reclaims stale jobs every 60 seconds (jobs with expired visibility timeout)
- Runs budget reconciliation every 60 seconds (releases expired reservations)
- On failure: exponential backoff retry (max 3 attempts), then permanent failure

### 4.4 Budget Enforcement — Two-Layer Approach

**Pre-Admission (at request time):**
1. Count active reservations for the user (NOT sessions)
2. Create session in `AWAITING_BUDGET_RESOLUTION` (pre-admission, not counted as active)
3. Evaluate 6 limits: daily USD, daily tokens, daily blog count, concurrent sessions, per-session cost, per-session tokens
4. If any limit exceeded: HTTPException → transaction rolls back → no orphan session
5. If all limits pass: create reservation, transition session to QUEUED

**Post-Finalization (after pipeline completes):**
1. **Layer 1 — `assert_reservation_valid()`**: Verifies reservation is ACTIVE, lease not expired, daily cap not consumed
2. **Layer 2 — `assert_within_reservation()`**: Verifies total actual cost (gate-committed + finalization) fits within original reservation + tolerance ($0.005)
3. **`finalize_stage_costs()`**: Commits each stage cost to ledger, flags fallback estimates
4. **`finalize_reservation()`**: Releases unused portion, marks reservation COMMITTED

### 4.5 Idempotency

Redis-backed idempotency for `/internal/ai/blogs` endpoint:
- Key format: `idempotency:{scope}:{endpoint}:{key}`
- Uses Redis `SET NX` for atomic lock acquisition
- Fingerprint: SHA-256 of sorted JSON request body
- TTL: 24 hours
- States: NEW → IN_PROGRESS → CACHED (with response)

---

## 5. The Concurrency Issue — Problem, Root Cause, and Fix

### 5.1 The Problem

Users were hitting HTTP 402 errors with reason: `"Concurrent session limit exhausted: 2 active of 2 limit"` even though they only had 1 backend running and no real active sessions. The `remaining_active_session_slots` was 0, but `daily_remaining_usd` and `daily_remaining_blog_count` were fine.

### 5.2 Root Cause

The original admission flow in `_create_canonical_generation()` was:

```
1. Create BlogSession (status=QUEUED)     ← Session created first
2. Call reserve_generation_budget()         ← Budget check happens second
3. If budget fails → HTTPException         ← Session already exists!
```

When step 2 failed (budget or concurrency exceeded), the session was already flushed to the database inside the transaction. The `HTTPException` raised at step 3 should have triggered a rollback via SQLAlchemy's `session.begin()` context manager. However, there were scenarios where the rollback didn't work as expected (e.g., exception handling edge cases, or sessions from previous code versions). The result was **orphan sessions** in QUEUED or PROCESSING status that counted as "active" and permanently blocked new requests.

Additionally, `count_active_for_end_user()` included `AWAITING_BUDGET_RESOLUTION` in the active statuses list, meaning even properly-created pre-admission sessions were counted as active, creating false positives in the concurrent session check.

The concurrent session check also used the `blog_sessions` table as the source of truth (counting sessions by status), rather than the `budget_reservations` table (counting active reservations). This conflated execution lifecycle (session states) with admission truth (active reservations).

### 5.3 The Fix

**Three coordinated changes:**

**A. Atomic Admission Flow:**
- Session starts in `AWAITING_BUDGET_RESOLUTION` (pre-admission, not counted as active)
- Budget check uses `budget_reservations` table count (not session count)
- If budget fails: HTTPException → transaction rolls back → no orphan session
- If budget passes: session transitions to QUEUED, reservation created, budget committed

**B. Reservation Table as Concurrency Truth:**
- Added `count_active_reservations_for_end_user()` to `BudgetRepository`
- All concurrency checks now use reservation count, not session count
- `count_active_for_end_user()` no longer includes `AWAITING_BUDGET_RESOLUTION` in active statuses

**C. Reconciliation Safety Net:**
- `reconcile_stale_pre_admission_sessions()` cleans up sessions stuck in `AWAITING_BUDGET_RESOLUTION` for > 15 minutes
- Runs alongside existing `reconcile_expired_reservations()` in the worker loop

### 5.4 Invariant Enforced

> A session must never become active unless an active budget reservation exists for it.

**Equivalent invariants:**
- Runnable session ⇔ active reservation exists
- `active_session_count` must equal `COUNT(budget_reservations WHERE status = 'active')`
- `AWAITING_BUDGET_RESOLUTION` must never count as active

---

## 6. Remaining Issues in the Database Schema

### 6.1 `user_budget_states.active_session_count` Is a Cached Counter

The `active_session_count` field in `user_budget_states` is a mutable counter that is supposed to mirror the count of active reservations. However, it can drift from the actual reservation count if:
- A reservation is created but the counter isn't incremented (e.g., due to a crash between the two operations)
- A reservation is released but the counter isn't decremented
- Reconciliation cleans up a reservation but the counter update fails

**Current mitigation:** The counter is used for the concurrency check in `_evaluate_limits()`, but the reservation count is now used as the admission-time override (`current_active_sessions_override`). The counter can still drift but the system self-corrects on each new admission.

**Recommendation:** Consider removing `active_session_count` from `user_budget_states` entirely and always querying the reservation table directly. This eliminates the dual-write problem.

### 6.2 `reconcile_stale_pre_admission_sessions()` Uses Raw SQL

The `reconcile_stale_pre_admission_sessions()` method in `BudgetService` uses `sqlalchemy.update()` directly via `self._session.execute(stmt)`. However, `BudgetService` does not own a `_session` attribute — it delegates to repositories that each have their own session. This method would fail at runtime if called directly.

**Status:** This method exists in the codebase but is not yet wired into the worker reconciliation loop. It needs to be either:
- Moved to a repository class that owns the session, or
- Called with an explicit session passed as a parameter, or
- Integrated into the worker's reconciliation loop with proper session management

### 6.3 `AWAITING_BUDGET_RESOLUTION` Dual Semantics

This status is used for two different purposes:
1. **Pre-admission** — Session created but budget not yet validated (canonical.py admission flow)
2. **Mid-pipeline exhaustion** — Session was running but budget ran out and `soft_stop_enabled=True` (stage_executor.py)

The `reconcile_stale_pre_admission_sessions()` method cleans up ALL sessions in `AWAITING_BUDGET_RESOLUTION` older than 15 minutes, which would also clean up type-2 sessions. Type-2 sessions may need a longer retention window for admin review.

**Recommendation:** Add a `budget_exhaustion_reason` field to `blog_sessions` to distinguish pre-admission from mid-pipeline exhaustion, or use a separate status (e.g., `AWAITING_BUDGET_TOPUP`) for mid-pipeline exhaustion.

### 6.4 Dual Budget Guard Systems

Two budget enforcement systems coexist:
- **Legacy guard** (`budget_guard.py`): Per-agent token limits with 20% buffer, used directly by agents
- **Canonical system** (`BudgetService`): Estimated stage tokens for pre-admission checks, used by API/worker

There is no integration between them. The legacy guard could reject a request that the canonical system approved, or vice versa.

**Recommendation:** Deprecate the legacy guard entirely and migrate all enforcement to `BudgetService`. The canonical system already has per-session token limits that serve the same purpose.

### 6.5 `BlogSession` Status Enum Not Enforced at Database Level

The `status` column uses a PostgreSQL enum, but the transition rules (e.g., QUEUED → PROCESSING is valid, but QUEUED → COMPLETED is not) are only enforced by application code. There is no database trigger or constraint to prevent invalid state transitions.

**Recommendation:** Add a database trigger or CHECK constraint that validates state transitions, or accept that the application code is the sole enforcer and ensure all state transitions go through `BlogSessionRepository.update_status()`.

### 6.6 Notification Service Incompatible with Service Mode

`NotificationService._resolve_local_user_id()` tries to cast `end_user.external_user_id` to int. This works in standalone mode (where `external_user_id` is the auth_users.id as a string) but fails silently in service mode (where it's a freeform string from upstream). Notifications are silently not created for service-mode users.

**Recommendation:** Make notification creation optional for service-mode users, or use a different notification mechanism (e.g., webhook events).

### 6.7 `export_jobs` Table Is Unused

The `export_jobs` table exists in the schema but there are no routes or code that create export jobs. It appears to be a placeholder for future functionality.

**Status:** Not a bug, but dead schema. Consider removing or implementing the export feature.

### 6.8 `budget_reservations` Unique Constraint May Prevent Revision Reservations

The unique constraint on `budget_reservations` is `(blog_session_id, reservation_scope, iteration_number, status)`. If an initial reservation is still ACTIVE when a revision reservation is created, the different `reservation_scope` values (`session_initial` vs `session_revision`) allow both to coexist. However, if the initial reservation is COMMITTED (not RELEASED), creating a revision reservation requires the initial reservation to be in a terminal state first.

**Status:** Currently handled correctly by the code — `finalize_reservation()` marks the initial reservation as COMMITTED before revisions can be requested. But the constraint design is fragile.

### 6.9 No Index on `blog_sessions.end_user_id`

The `blog_sessions` table has an index on `status` and `external_request_id`, but not on `end_user_id`. The `count_active_for_end_user()` query filters by `end_user_id` and `status`, which would benefit from a composite index.

**Recommendation:** Add `CREATE INDEX ix_blog_sessions_end_user_id_status ON blog_sessions(end_user_id, status)`.

### 6.10 `budget_ledger_entries` Growing Without Partitioning

The `budget_ledger_entries` table is append-only and grows with every reserve/commit/release operation. There is no partitioning by date or `window_start`. Over time, this table will grow unbounded.

**Recommendation:** Add range partitioning by `created_at` (monthly or weekly) for efficient queries and archival.

---

## 7. Key Files Reference

| File | Purpose |
|------|---------|
| `backend/src/api/routes/canonical.py` | All blog generation routes (standalone + service) |
| `backend/src/api/main.py` | FastAPI app, lifespan, middleware |
| `backend/src/models/orm_models.py` | All 16 ORM models |
| `backend/src/models/schemas.py` | Pydantic schemas for API contracts |
| `backend/src/models/repositories/budget_repository.py` | Budget policy, state, reservations, ledger |
| `backend/src/models/repositories/blog_session_repository.py` | BlogSession CRUD |
| `backend/src/services/budget_service.py` | Budget enforcement service (924 lines) |
| `backend/src/services/budget_exceptions.py` | Budget exception hierarchy |
| `backend/src/services/revision_service.py` | HITL review + revision loops |
| `backend/src/agents/pipeline_v2.py` | ADK pipeline orchestration |
| `backend/src/workers/blog_worker.py` | Background worker loop |
| `backend/src/workers/stage_executor.py` | Pipeline execution + budget finalization |
| `backend/src/core/task_queue.py` | Redis task queue |
| `backend/src/core/idempotency.py` | Redis idempotency store |
| `backend/src/config/budget_config.py` | Budget settings + model pricing |
| `backend/alembic/versions/001_canonical_schema.py` | Canonical tables + enums |
| `backend/alembic/versions/005_atomic_budget_guard.py` | Budget state + reservations tables |

---

## 8. Summary

Blogify AI is a production-grade AI blog generation system with a sophisticated budget enforcement layer. The database schema supports multi-tenant isolation, atomic budget reservations with crash-safe accounting, and immutable audit ledger. The recent concurrency fix ensures that session creation and budget admission are atomic, preventing orphan sessions from blocking future requests. The remaining schema issues are mostly about dual-write risks (cached counters), dead schema (export_jobs), and missing indexes that should be addressed incrementally.
