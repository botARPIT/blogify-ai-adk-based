# Blogify Backend Architecture

## Summary

This document is the current architecture source of truth for the Blogify backend in this repository.

The live system is built around:
- a FastAPI API service
- PostgreSQL as the canonical persistence layer
- Redis for queueing, rate limiting, and session support
- background worker processes for asynchronous AI execution
- Prometheus, Grafana, and Tempo for observability

Older documentation in this repo that describes a prior edge-oriented design is historical only.

## System Overview

### Runtime Components

- API service:
  - FastAPI application served from `src.api.main:app`
  - handles browser auth, internal API-key auth, validation, canonical session APIs, and operator APIs
- Worker service:
  - background process started from `src.workers.blog_worker`
  - consumes queued generation jobs and runs the pipeline
- PostgreSQL:
  - canonical source of truth for sessions, versions, budgets, review events, notifications, and service-client state
- Redis:
  - job queue
  - worker heartbeat registry
  - rate limiting
  - ADK/session state support where required
- Observability stack:
  - Prometheus for metrics
  - Grafana for dashboards
  - Tempo via OTLP for traces

### High-Level Flow

1. A browser client or internal service submits a request to the FastAPI API.
2. The API authenticates the caller and validates budget/rate-limit constraints.
3. For generation requests, the API creates a canonical `blog_session` record and enqueues a job in Redis.
4. A worker dequeues the job and runs the AI pipeline.
5. The worker persists stage results, versions, review state, and budget ledger entries in PostgreSQL.
6. Clients poll or query canonical APIs for state and content.

The pipeline phase/loop naming decision and runtime semantics are documented in:
- [ADR-2026-06-17-pipeline-phase-and-loop-semantics.md](/home/bot/repos/development/blogify-ai-adk-prod/backend/docs/ADR-2026-06-17-pipeline-phase-and-loop-semantics.md)

## Request And Execution Flows

### Standalone Browser Flow

1. The user authenticates through `/api/v1/auth/*` using a cookie-based local auth flow.
2. The browser calls `POST /api/v1/blogs/generate`.
3. The API resolves the standalone identity into:
   - `ServiceClient` = standalone default
   - `Tenant`
   - `EndUser`
4. The API performs canonical budget preflight against tenant/end-user policy.
5. The API creates a `blog_sessions` row and reserves budget in `budget_ledger_entries`.
6. The API enqueues the generation job in Redis and returns queued status.
7. The worker runs the pipeline and persists:
   - agent runs
   - blog versions
   - session status transitions
   - budget commit/release entries
8. The user accesses:
   - `GET /api/v1/blogs`
   - `GET /api/v1/blogs/{session_id}`
   - `GET /api/v1/blogs/{session_id}/detail`
   - review routes where applicable

### Internal Service Flow

1. The caller authenticates with `X-Internal-Api-Key`.
2. The API validates the service client and applies service request limits.
3. For `POST /internal/ai/blogs`, the API performs:
   - service-client daily budget preflight
   - tenant/end-user canonical budget preflight
4. If allowed, the API resolves:
   - `ServiceClient`
   - `Tenant`
   - `EndUser`
5. The API creates and queues the canonical session.
6. Internal callers use read APIs under `/internal/ai/blogs/*` and `/internal/ai/budgets/*`.

## Blog Generation Runtime Phases

Redis is queue transport, PostgreSQL is the canonical state store, and ADK session state is
rehydrated from persisted DB snapshots before resumed execution paths continue.

| Session / job phase | Trigger source | Queue entry phase | Worker executor entrypoint | Pipeline function called | Agent sequence that runs | Next state produced |
|---|---|---|---|---|---|---|
| `fresh_generation` | `POST /blogs/generate` | `fresh_generation` | `_execute_fresh_generation` | `run_pipeline()` | `intent_agent` -> `outline_agent` -> `outline_review_agent` -> pause if outline confirmation is requested -> otherwise `research_agent` -> `full_pipeline_draft_refinement_loop` | Usually `AWAITING_OUTLINE_REVIEW`, otherwise `AWAITING_FINAL_REVIEW` |
| `AWAITING_OUTLINE_REVIEW` | Full pipeline paused at `review_generated_outline` | None while waiting | None while waiting | None while waiting | No worker execution; user review endpoint updates the active version/session and enqueues `resume_outline` | `resume_outline` is enqueued after user approval/edit |
| `resume_outline` | Outline approval/edit submission | `resume_outline` | `_execute_resume_outline` | `resume_pipeline()` | Resumes the paused full app pipeline at the outline confirmation boundary, then continues into `research_agent` -> `full_pipeline_draft_refinement_loop` | `AWAITING_FINAL_REVIEW` |
| `research_phase` | Stale-worker recovery after outline approval has already been consumed | `research_phase` | `_execute_research_phase` | `run_pipeline_from_phase("research_phase")` | `research_agent` -> `phase_resume_draft_refinement_loop` | `AWAITING_FINAL_REVIEW` |
| `revision` | Final review action `revision_requested` | `revision` | `_execute_revision` | `run_pipeline_from_phase("research_phase")` | `research_agent` -> `phase_resume_draft_refinement_loop` | `AWAITING_FINAL_REVIEW` |
| `AWAITING_FINAL_REVIEW` | Successful completion of research + drafting/editing | None while waiting | None while waiting | None while waiting | No worker execution; user may approve, request revision, or reject | `COMPLETED`, `revision` enqueued, or `REJECTED` |

Clarification for `revision`:

- the persisted job phase is `revision`
- the execution rerun entrypoint is still the `research_phase` phase runner

## Architecture Diagram Review

The supplied system architecture diagram is broadly directionally correct, but it needs refinement
to match the current implementation.

### Correct aspects

- FastAPI -> Redis enqueue -> Worker is broadly correct
- Worker -> PostgreSQL persistence is correct
- Outline review and final draft review are both human decision points
- Reaper is a separate recovery component interacting with Redis and PostgreSQL

### Needs refinement

- The diagram should show two distinct writer/editor loops, not one generic path.
- `resume_outline` is not a fresh start from intent; it resumes a paused full app pipeline at the outline confirmation boundary.
- `revision` does not resume the full app pipeline; it runs the phase runner from `research_phase`.
- `research_phase` recovery should appear as a separate recovery entrypoint after outline approval has already been consumed.
- `AWAITING_OUTLINE_REVIEW` is a persisted wait state, not a continuously running agent node.
- `AWAITING_FINAL_REVIEW` is an application review state, not an ADK resumable gate.
- Final review must show three outcomes:
  - approve
  - revision requested
  - reject
- Reaper should not be labeled as polling only “failed jobs”; it handles:
  - stale leases
  - stale Redis processing entries
  - queued-session reconciliation
- Redis should be described as transport, not system-of-record state.

### Admin / Operator Flow

1. The caller authenticates with `X-Admin-Api-Key`.
2. Operator routes under `/internal/admin/service-clients/*` allow:
   - service-client creation
   - listing and inspection
   - key rotation
   - suspend and activate
   - service-client daily budget configuration
3. Service-client budget policy is stored in `service_client_budget_policies`.
4. Current budget exhaustion is derived from the ledger for the current UTC day and is not a manually toggled flag.

## Canonical Data Model

### Core Entities

- `ServiceClient`
  - represents a caller/integration mode
  - owns tenants
  - may have a `ServiceClientBudgetPolicy`
- `ServiceClientBudgetPolicy`
  - explicit service-wide daily AI budget cap
  - used for temporary generation lockout until the next UTC reset
- `Tenant`
  - workspace/account boundary beneath a service client
- `EndUser`
  - actual budget-consuming user within a tenant
- `BudgetPolicy`
  - effective budget policy for default, tenant, or user-override scope
- `BudgetLedgerEntry`
  - append-only reserve/commit/release journal for canonical spend
- `BlogSession`
  - parent lifecycle record for a generation request
- `BlogVersion`
  - materialized content versions for a session
- `AgentRun`
  - per-stage or per-agent execution record
- `HumanReviewEvent`
  - review decisions and feedback trail
- `AuthUser`
  - local browser-authenticated user
- `UserNotification`
  - in-app notifications for workflow transitions

### Compatibility-Only Legacy Tables

The following are retained for compatibility or analytics and are not canonical authority:

- `User`
- `Blog`
- `CostRecord`

Canonical authority for current backend behavior is:
- sessions: `blog_sessions`
- versions: `blog_versions`
- budgets: `budget_ledger_entries`, `budget_policies`, `service_client_budget_policies`
- notifications: `user_notifications`

## Budget Model

### User And Tenant Budgets

Canonical user-facing generation flow uses effective policy resolution in this order:

1. user override
2. tenant policy
3. global default policy

Checks include:
- daily USD limit
- daily token limit
- per-session cost estimate

### Service-Client Daily Budgets

Internal service-mode generation also checks a service-wide daily USD budget.

Behavior:
- scope: entire `ServiceClient`
- source: `service_client_budget_policies`
- spend basis: derived from canonical ledger usage aggregated across all tenants/end users beneath that service client
- reset: next UTC midnight
- effect: blocks new generation requests only
- non-effect: does not block read-only internal session routes

### Ledger Semantics

The canonical ledger uses append-only entries:
- `reserve`
- `commit`
- `release`

Net daily spend is computed as:
- commits plus reserves minus releases

This model supports:
- preflight reservation
- actual stage commit
- rollback/release on failure
- consistent snapshot reporting

### Snapshot Versus Session-Specific Values

- `active_sessions`:
  - count of non-terminal canonical sessions for the end user
- `remaining_revision_iterations` in budget snapshots:
  - policy ceiling available to a new or active session context
- `remaining_revision_iterations` in session views:
  - `max(policy.max_revision_iterations_per_session - session.iteration_count, 0)`

These values should not be treated interchangeably.

## Observability

### Metrics

Prometheus metrics include:
- HTTP request counts and durations
- blog generation counts and durations
- agent invocation, token, and cost metrics
- budget exceeded counters
- service-client budget preflight/exhaustion counters
- judge decision and quality metrics
- rate-limit rejection counters

### Tracing

- tracing is initialized in the API
- OTLP export is wired to Tempo in local compose
- SQLAlchemy and FastAPI instrumentation are enabled when OTEL dependencies are present

### Dashboards

Grafana provisioning includes dashboards for:
- API overview
- pipeline overview
- budget and review operations

### Request Metadata

The middleware stack adds:
- `X-Request-ID`
- response timing headers
- rate-limit headers where applicable

## Deployment And Runtime

### Local Runtime

Local Docker Compose includes:
- API
- worker
- Redis
- Prometheus
- Grafana
- Tempo

### CI / Verification

Backend verification is run from `backend/` and should cover:
- unit tests
- smoke tests
- compose config validation
- syntax/import validation for touched modules

### Required Environment Variables

At minimum:
- `DATABASE_URL`
- `REDIS_URL`
- `GOOGLE_API_KEY`
- `TAVILY_API_KEY`

Production and staging additionally require:
- `JWT_SECRET_KEY`
- `ADMIN_API_KEY`
- explicit `CORS_ORIGINS`

### Logging Policy

- logging is structured with `structlog`
- stage and prod must use `json` log format
- sensitive fields are masked before rendering

## Security Model

### Browser Auth

- local cookie-based authentication
- CSRF checks on state-changing browser routes
- auth middleware marks and enforces protected browser routes

### Internal Service Auth

- `X-Internal-Api-Key`
- service-client validation through hashed API key lookup
- per-client request and blog-generation rate limits

### Admin Auth

- `X-Admin-Api-Key`
- separate from browser auth and service-mode API keys

## Historical Context

Several older docs in this repository describe a previous Cloudflare Workers and Prisma Accelerate architecture. Those documents are retained for planning history and audit context only. They are not the current implementation reference.

Use this document as the authoritative architecture description for the backend currently shipped from this repository.
