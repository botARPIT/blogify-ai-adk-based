# Blogify AI

Blogify AI is an asynchronous, human-reviewed blog-generation system. A FastAPI API records a durable generation request, Redis delivers it to a worker, and a Google ADK workflow produces a draft that a user reviews before publication.

## What it demonstrates

- Asynchronous API design with polling rather than long-running HTTP requests.
- A PostgreSQL outbox and Redis delivery queue so generation jobs survive API or worker failures.
- Worker leases and reaper-based recovery for abandoned work.
- Human review after the outline and final-editing stages.
- Versioned REST API, cookie-based local authentication, idempotent generation requests, and per-user quotas.
- Structured logs, Prometheus metrics, OpenTelemetry tracing, and Grafana dashboards.

## Demo flow

1. Register or sign in, then submit a topic, audience, and tone.
2. The API creates a session and durable outbox event, then dispatches a job to Redis.
3. The worker runs the Intent, Outline, Research, Writer, and Editor stages through Google ADK.
4. Review the generated outline; approving or revising it resumes the workflow.
5. Review the final draft, then read or export the completed blog.

## Architecture

### System context

![System context: the API records durable work in PostgreSQL, Redis delivers jobs to a worker, and the worker runs the Google ADK workflow.](docs/architecture/SystemArchitecture.png)

### Generation workflow

![Workflow: generation is queued, processed through the ADK stages, paused for outline and final reviews, and persisted as a completed blog.](docs/architecture/WorkflowDiagram.png)

### Multi-agent pipeline

![Multi-agent pipeline: fresh generation classifies intent and produces a reviewable outline; after human approval, research, writing, and editing produce a final draft for human review.](<docs/architecture/Blogify Content Generation Workflow.png>)

The editable source diagrams and architecture notes are in [docs/architecture](docs/architecture/README.md). The backend architecture reference covers the outbox, lease, recovery, observability, and security decisions in [docs/architecture/backend.md](docs/architecture/backend.md).

## Quick start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Node.js 20+ and pnpm, if running the frontend locally
- Google and Tavily API keys for live generation

### Configure and run the backend stack

```bash
cp backend/.env.dev backend/.env
# Edit backend/.env and set GOOGLE_API_KEY and TAVILY_API_KEY.

docker compose -f backend/docker-compose.yml up --build
```

This starts the API at `http://localhost:8000`, PostgreSQL, Redis, the worker, reaper, Prometheus, and Grafana. The API reference is available at `http://localhost:8000/docs`.

### Run the frontend

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

For a non-container local backend setup, use the documented scripts in [backend/README.md](backend/README.md).

## API

The canonical API prefix is `/api/v1`.

- Interactive OpenAPI: `http://localhost:8000/docs`
- Raw OpenAPI document: `http://localhost:8000/openapi.json`
- Postman collection: [postman/Blogify-AI.postman_collection.json](postman/Blogify-AI.postman_collection.json)
- Human-facing workflow guide: [docs/API.md](docs/API.md)

The main client flow is:

```text
POST /auth/register or /auth/login
POST /blogs/generate
GET  /blogs/{session_id}/status
GET  /blogs/{session_id}/outline
POST /blogs/{session_id}/outline/review
POST /blogs/{session_id}/final-review
GET  /blogs/{session_id}/content
```

## Testing and verification

```bash
cd backend

# Unit and API-contract tests
.venv/bin/pytest tests/unit -q

# Tests that require dedicated PostgreSQL and Redis services
export BLOGIFY_TEST_DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/blogify_test'
export BLOGIFY_TEST_REDIS_URL='redis://localhost:6379/15'
.venv/bin/pytest tests/e2e -q
```

The lifecycle E2E suite scripts the provider-facing executor, so it exercises the API-to-PostgreSQL/Redis/worker path without calling Google or Tavily. See [backend/tests/e2e/README.md](backend/tests/e2e/README.md) before running it.

## Operations

- Health: `GET /api/v1/health`, with liveness, readiness, detailed, and startup variants.
- Metrics: `GET /metrics` (protect this endpoint in non-local environments).
- Dashboards: Prometheus at `http://localhost:9090`; Grafana at `http://localhost:3001` for the local Compose stack.
- Database migrations: `bash backend/scripts/init_db.sh`.
- More detail: [observability](docs/backend/observability.md), [performance plan](docs/backend/performance/slo-sli-and-stress-plan.md), and [Azure deployment runbook](docs/runbooks/azure-vm.md).

## Current limitations

- Generation depends on external model and research providers; provider latency and availability affect completion time.
- The checked-in deployment path is Docker Compose. Kubernetes and multi-region failover are intentionally out of scope.
- The project has focused unit, contract, and integration coverage, but capacity claims require a representative deployed load test.
- Document export requires Pandoc to be available in the API runtime.

## Repository layout

```text
backend/     FastAPI API, worker, reaper, persistence, monitoring, and tests
frontend/    React/Vite browser client
docs/        Architecture, API, operational runbooks, and incident notes
postman/     Importable API collection
```

## License

MIT
