# Blogify backend architecture

## Purpose

Blogify accepts a blog brief, executes an asynchronous Google ADK workflow, and pauses at two human-review checkpoints. PostgreSQL is the durable workflow authority; Redis is the queue and delivery mechanism.

See the [system context](SystemArchitecture.png) and [generation workflow](WorkflowDiagram.png) diagrams for the visual overview.

## Runtime components

| Component | Responsibility |
| --- | --- |
| FastAPI API | Cookie or bearer authentication, input validation, session reads, generation and review commands. |
| PostgreSQL | Authoritative state for sessions, versions, outbox events, leases, reviews, budgets, and research sources. |
| Redis | Job delivery, worker coordination, rate limiting, and short-lived runtime support. |
| Worker | Claims a queued outbox event and session lease, runs the workflow, and persists durable results. |
| Reaper | Relays undispatched outbox events and recovers expired claims or leases. |
| Google ADK workflow | Runs Intent, Outline, Research, Writer, and Editor stages; provider calls use configured model and research adapters. |

## Request and recovery flow

1. An authenticated browser calls `POST /api/v1/blogs/generate`.
2. The API commits the blog session, budget reservation, and outbox event to PostgreSQL in one transaction.
3. The API attempts a fast-path Redis enqueue; the reaper later relays any undispatched event.
4. A worker dequeues the delivery, claims the outbox event and session lease, then runs the ADK stage for that job phase.
5. The worker persists stage data, versions, review events, and status transitions to PostgreSQL before acknowledging delivery.
6. The user polls the API and submits an outline or final-review decision when the session reaches a human-review state.
7. A stale lease or incomplete delivery is retried through the reaper and outbox protocol.

## State model

The canonical session states are:

```text
QUEUED → PROCESSING → AWAITING_OUTLINE_REVIEW → QUEUED
                  └→ AWAITING_FINAL_REVIEW → COMPLETED
```

`FAILED`, `REJECTED`, `AGENT_REJECTED`, and `CANCELLED` are terminal states. A final revision request returns the session to `QUEUED`; an outline decision also queues the appropriate continuation phase.

## Persistence model

The ORM declares the current schema. The principal tables are:

- `auth_users` and `user_blog_quotas`
- `blog_sessions`, `blog_versions`, and `blog_review_events`
- `workflow_outbox_events` and `session_leases`
- `agent_runs` and `research_sources`
- `budget_accounts`, `budget_ledger`, and `session_reservations`
- `tone_catalog`

The [database schema diagram](blogify-database-schema.excalidraw) is maintained from those declarations. Verify it against Alembic migrations and a deployed database before using it as live-schema evidence.

## Public API boundary

The published API is under `/api/v1`; its OpenAPI document is served from `/openapi.json`. The browser flow uses `/api/v1/auth/*`, `/api/v1/blogs/*`, and `/api/v1/tones`. The current repository does not publish the older `/internal/ai/*` service-client routes.

Read [the API guide](../API.md) for client usage and [the Postman collection](../../postman/Blogify-AI.postman_collection.json) for executable examples.

## Observability

The API, worker, and reaper emit structured logs, Prometheus metrics, and OpenTelemetry traces. Local Compose starts Prometheus and Grafana. The production Compose profile also defines Tempo and an OpenTelemetry Collector. See [observability](../backend/observability.md) for endpoint and dashboard details.

## Security and ownership

- Browser clients authenticate through the local `auth_token` cookie; bearer tokens are accepted for non-browser clients.
- Blog reads and mutations enforce ownership through the authenticated user context.
- Secrets are environment variables; no secret values are stored in the repository.
- The API validates generation input, enforces a per-user daily quota, and supports stable idempotency keys for retry-safe creation.
