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
