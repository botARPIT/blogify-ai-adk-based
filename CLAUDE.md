# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)

```bash
cd backend
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Database migrations
alembic upgrade head

# Run API server (port 8000)
PYTHONPATH=. uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Run worker (in separate terminal)
PYTHONPATH=. python -m src.workers.blog_worker

# Tests
pytest                              # All tests
pytest -m unit                     # Unit tests only
pytest -m integration              # Integration tests only
pytest -v tests/unit/test_core.py  # Single test file
pytest -k test_name                # Single test by name

# Linting/formatting
black src/ tests/
ruff check src/ tests/
mypy src/

# Health check
curl http://localhost:8000/api/health
curl http://localhost:8000/api/health/ready
curl http://localhost:8000/metrics
```

### Frontend (React/Vite)

```bash
cd frontend
npm install

# Development server
npm run dev

# Production build
npm run build

# Lint
npm run lint
```

## Architecture

### System Overview

Blogify AI is a session-based blog generation system with human-in-the-loop (HITL) review gates. The architecture separates concerns across:

- **API Process** (`src.api.main:app`): FastAPI handling HTTP requests, no LLM calls
- **Worker Process** (`src.workers.blog_worker`): Background job processor consuming Redis queue, executes LLM pipeline
- **PostgreSQL**: Persistent storage for sessions, users, budgets, reviews
- **Redis**: Rate limiting, idempotency cache, task queue, session store

### Key Design Patterns

**Idempotent Mutations**: All mutating endpoints support `Idempotency-Key` header for safe retries:
- `POST /api/v1/blogs/generate`
- `POST /api/v1/blogs/{session_id}/outline/review`
- `POST /api/v1/blogs/{session_id}/review`

Reuse the same key for retries; different payload returns 409. Completed outcomes are cached and replayed without re-executing.

**Budget Enforcement**: Dual-layer budget system (Phase 3):
- End-user budgets via `BudgetService` (per-user daily limits)
- Service client budgets via `ServiceClientBudgetService` (upstream API consumers)
Budget exhaustion returns 402 with structured `BudgetExhaustedDetail`

**Guard Layers**: Input/output validation at pipeline boundaries (`src.guards/`):
- `rate_limit_guard`: Redis-backed rate limiting
- `input_guard`: Pre-execution validation
- `output_guard`: Post-execution validation
- `budget_guard`: Token and cost budget enforcement

**Session State Machine**: Blog generation progresses through canonical statuses:
```
queued → intent_clarification → outlining → outline_review → writing → reviewing → completed|failed
```
Review gates (outline_review, reviewing) pause for human approval.

### Project Structure

**Backend** (`backend/src/`):
- `api/`: FastAPI routes, auth, middleware
  - `routes/canonical.py`: Main blog generation and review endpoints
  - `auth.py`: Cookie-based JWT auth
  - `middleware.py`: Request ID, CORS, error handling
- `agents/`: LLM agent definitions and pipeline_v2
- `controllers/`: (legacy cleanup in progress)
- `core/`: Shared infrastructure (errors, idempotency, redis, task queue, circuit breaker)
- `guards/`: Validation and rate limiting guards
- `models/`: SQLAlchemy ORM, Pydantic schemas, repository pattern
- `services/`: Business logic (budget, notification, revision, outline review)
- `workers/`: Background worker and stage executor
- `config/`: Environment-based configuration
- `alembic/`: Database migrations

**Frontend** (`frontend/src/`):
- `pages/`: Route components (Compose, Dashboard, OutlineReview, FinalReview, Output, Budget)
- `lib/api/`: API client with standardized error handling
- `hooks/`: SWR-based data fetching hooks
- `context/`: Auth context for session management
- `components/`: Shared UI components

### Route Surfaces

**Browser-facing** (`/api/v1/*`):
- Auth: `/api/v1/auth/*` (login, logout, me)
- Blog generation: `/api/v1/blogs/*` (generate, get, outline, review, versions)
- Budget: `/api/v1/budgets/me`
- Notifications: `/api/v1/notifications/*`

**Internal service** (`/internal/ai/*`):
- Protected by `X-Internal-Api-Key` header
- Used by upstream backends integrating Blogify as a service
- Supports same idempotency semantics

### Environment Configuration

Required in `backend/.env`:
- `DATABASE_URL`: PostgreSQL connection (asyncpg driver)
- `REDIS_URL`: Redis connection
- `GOOGLE_API_KEY`: LLM provider
- `JWT_SECRET_KEY`: Cookie auth signing
- `ADMIN_API_KEY`: If admin routes enabled
- `CORS_ORIGINS`: Allowed frontend origins

### Error Handling

Centralized in `src.core.errors`:
- `BlogifyError`: Base exception class
- `ErrorCode`: Standardized error codes (VALIDATION_ERROR, BUDGET_EXCEEDED, etc.)
- FastAPI exception handlers return frontend-safe JSON with `error_code`, `message`, `request_id`

Frontend uses `ApiError` class (`frontend/src/lib/api/base.ts`) to parse and display user-friendly messages.

### Testing Strategy

- **Unit tests** (`tests/unit/`): Fast, isolated, mock external services
- **Integration tests** (`tests/integration/`): Hit real database, test full workflows
- **Smoke tests** (`tests/smoke/`): Basic connectivity and health checks
- **Eval tests** (`tests/eval/`): LLM output quality evaluation

Use markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`

### Database Migrations

Alembic is source of truth. Always run `alembic upgrade head` before starting API. Migration files in `backend/alembic/versions/`.

### Docker/Deployment

- `backend/docker-compose.yml`: API, worker, Redis, Prometheus, Tempo, Grafana (NOT PostgreSQL)
- `backend/kubernetes/`: K8s manifests
- `backend/monitoring/`: Observability configs

Separate infrastructure for PostgreSQL required; set `DATABASE_URL` accordingly.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
