# Blogify AI - Deep Technical Architecture Report

**Date:** 2026-01-20  
**Auditor:** Senior Backend Architect  
**Service:** blogify-ai-adk-prod  
**Codebase Version:** main branch, commit e98743c  

---

## 1. Service Boundaries & Responsibilities

### What This Service Is Responsible For

1. **Blog Generation Orchestration**: Coordinates a multi-stage LLM pipeline (intent → outline → research → writing)
2. **Human-in-the-Loop (HITL) Workflow**: Pauses for human approval at intent and outline stages
3. **State Management**: Persists pipeline state (stage_data, current_stage) for HITL workflow
4. **Rate Limiting**: Enforces per-user and global request/blog limits
5. **Cost Tracking**: Records token usage and cost per blog generation
6. **Research Integration**: Fetches external sources via Tavily API

### What This Service Does NOT Handle

1. **User Authentication**: Explicitly delegated to external auth service (no JWT validation, no login)
2. **User Registration/Management**: Only creates stub user records for tracking
3. **Payment/Billing**: No payment integration; cost tracking is informational only
4. **Content Storage/CDN**: No image/media handling; text only
5. **Email/Notifications**: No notification system
6. **Blog Publishing**: No publishing to external platforms

### External Dependencies

| Dependency | Purpose | Protocol | Required |
|------------|---------|----------|----------|
| **PostgreSQL (Neon)** | Primary data store | asyncpg | Yes |
| **Redis** | Rate limiting, counters | redis-py async | Yes |
| **Google Gemini** (via ADK) | LLM for all agents | gRPC/HTTP | Yes |
| **Tavily API** | External research/sources | HTTP REST | Yes |

### Stateless vs Stateful

**Verdict: STATEFUL**

The service maintains in-memory state that cannot be shared across instances:

```python
# pipeline.py:44
self._session_service = InMemorySessionService()
```

This `InMemorySessionService` stores ADK session state. If a request hits a different instance mid-generation, the session is lost. **This is a critical scalability issue.**

---

## 2. API Design

### Endpoint Inventory

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Service info |
| GET | `/docs` | Swagger UI |
| GET | `/metrics` | Prometheus metrics |
| GET | `/api/health` | Basic health |
| GET | `/api/health/live` | Liveness probe |
| GET | `/api/health/ready` | Readiness probe |
| GET | `/api/health/detailed` | Full dependency check |
| POST | `/api/v1/blog/generate` | Start blog generation |
| POST | `/api/v1/blog/approve` | Approve/reject stage |
| GET | `/api/v1/blog/status/{session_id}` | Get generation status |
| GET | `/api/v1/blog/content/{session_id}` | Get final content |
| GET | `/api/v1/costs` | Cost tracking |
| GET | `/api/v1/system/info` | System info |

### Detailed Endpoint Definitions

#### POST `/api/v1/blog/generate`

```python
# Request Schema (BlogGenerationRequest)
{
    "user_id": str,           # Required, any string
    "topic": str,             # Required, 10-500 chars
    "audience": str | None,   # Optional, max 200 chars
    "sync": bool              # Optional, default False
}

# Response Schema (BlogGenerationResponse)
{
    "session_id": str,
    "status": str,            # "initiated" | "completed"
    "stage": str | None,      # "intent" | "outline" | "final"
    "message": str,
    "data": {
        "blog_id": int,
        "intent_result": {...},
        ...
    }
}
```

**Authentication:** NONE  
**Authorization:** NONE  
**Idempotency:** NOT IMPLEMENTED (same request creates new blog each time)

#### POST `/api/v1/blog/approve`

```python
# Request Schema
{
    "session_id": str,        # Required, UUID
    "approved": bool,         # Required
    "feedback": str | None    # Optional, for rejections
}

# Response Schema
{
    "session_id": str,
    "status": str,
    "stage": str,
    "message": str,
    "data": {...}
}
```

**Authentication:** NONE  
**Authorization:** NONE - ANY user can approve ANY session (security vulnerability)

---

## 3. Authentication & Authorization Model

### End-to-End Request Authentication

**Implementation: NONE**

```python
# blog.py:42
async def generate_blog(request: BlogGenerationRequest):
    # No authentication check
    # user_id is simply trusted from request body
    result = await blog_controller.generate_blog_sync(
        user_id=request.user_id,  # ← Attacker-controlled
        ...
    )
```

### Token Format

Not applicable - no tokens are validated.

### Token Issuer

External auth service (not integrated).

### Token Validation

```python
# Expected but NOT implemented:
# - No Authorization header check
# - No JWT signature validation
# - No token expiry check
```

### Missing/Expired Token Behavior

Requests are processed regardless. Any client can:
- Generate blogs as any user_id
- Approve any session
- View any user's content

### Service-to-Service Auth

Not implemented. The service makes unauthenticated calls to:
- Google Gemini API (uses API key from env)
- Tavily API (uses API key from env)

---

## 4. Data Model & Storage

### Databases Used

| Database | Type | Purpose | Location |
|----------|------|---------|----------|
| PostgreSQL | Relational | Primary data | Neon Cloud |
| Redis | Key-Value | Rate limiting | Local/Docker |

### Schema Definition

#### Table: `users`
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    daily_budget_usd FLOAT DEFAULT 1.0,
    daily_blogs_limit INTEGER DEFAULT 10,
    total_cost_usd FLOAT DEFAULT 0.0,
    total_blogs_generated INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Table: `blogs`
```sql
CREATE TABLE blogs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id),
    session_id VARCHAR(255) UNIQUE NOT NULL,
    topic VARCHAR(500) NOT NULL,
    audience VARCHAR(255),
    title VARCHAR(255),
    content TEXT,
    word_count INTEGER DEFAULT 0,
    sources_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'in_progress',  -- in_progress, completed, failed
    current_stage VARCHAR(50),
    stage_data JSONB,              -- Stores intermediate pipeline state
    total_cost_usd FLOAT DEFAULT 0.0,
    total_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

#### Table: `cost_records`
```sql
CREATE TABLE cost_records (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id),
    blog_id INTEGER REFERENCES blogs(id),
    session_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost_usd FLOAT DEFAULT 0.0,
    latency_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Persisted vs Transient Data

| Data | Storage | Persistence |
|------|---------|-------------|
| Blog content | PostgreSQL | Permanent |
| Pipeline state (stage_data) | PostgreSQL | Permanent |
| User records | PostgreSQL | Permanent |
| Cost records | PostgreSQL | Permanent |
| Rate limit counters | Redis | TTL (60s-24h) |
| ADK session state | In-Memory | Lost on restart |

### Source of Truth

This service is the **source of truth** for:
- Generated blog content
- Blog generation history
- Cost/token tracking
- Rate limit state (Redis)

### Consistency Guarantees

- **PostgreSQL:** ACID transactions via SQLAlchemy
- **Redis:** Eventual consistency (no transactions for rate limits)
- **Cross-store:** No distributed transactions (potential inconsistency between PostgreSQL and Redis)

---

## 5. Request Lifecycle (Critical Path)

### Synchronous Blog Generation (`sync=true`)

```
1. HTTP Request → FastAPI
   ↓
2. RequestIDMiddleware generates X-Request-ID
   ↓
3. blog.py:generate_blog() validates Pydantic schema
   ↓
4. blog_controller.generate_blog_sync()
   ↓
5. blog_service.generate_blog_sync()
   │
   ├─ 5a. db_repository.get_or_create_user() [DB WRITE]
   │
   ├─ 5b. db_repository.create_blog() [DB WRITE]
   │
   ├─ 5c. pipeline.run_full_pipeline()
   │       │
   │       ├─ 5c1. run_intent_stage()
   │       │       └─ _run_agent(intent_agent) [GEMINI API - 2-5s]
   │       │
   │       ├─ 5c2. run_outline_stage()
   │       │       └─ _run_agent(outline_agent) [GEMINI API - 3-8s]
   │       │
   │       ├─ 5c3. run_research_stage()
   │       │       └─ research_topic() [TAVILY API - 2-10s]
   │       │
   │       └─ 5c4. run_writing_stage()
   │               └─ _run_agent(writer_agent) [GEMINI API - 10-30s]
   │
   └─ 5d. db_repository.update_blog() [DB WRITE]
   ↓
6. JSON Response

Total Time: 20-60 seconds (BLOCKING)
```

### HITL Workflow (Two Requests)

**Request 1: Initiate**
```
POST /blog/generate → Creates blog → Runs intent_stage → Returns session_id
```

**Request 2: Approve**
```
POST /blog/approve → Fetches blog → Runs remaining stages → Returns content
```

### Blocking Points

| Operation | Typical Latency | Blocking |
|-----------|-----------------|----------|
| DB Write | 5-50ms | Yes |
| Gemini API | 2-30s | Yes |
| Tavily API | 2-10s | Yes |

**Critical Issue:** All LLM calls are blocking. A single slow Gemini response blocks the entire request.

---

## 6. LLM Integration Architecture

### Provider

**Google Gemini** via `google-adk` (Agent Development Kit)

### Models Used

```python
# config/models.py
INTENT_MODEL = "gemini-1.5-flash"      # Fast, cheap
OUTLINE_MODEL = "gemini-1.5-flash"     # Fast, cheap
WRITER_MODEL = "gemini-1.5-pro"        # Higher quality
EDITOR_MODEL = "gemini-1.5-pro"        # Higher quality
```

### Prompt Construction

Prompts are hardcoded strings with f-string interpolation:

```python
# pipeline.py:87-95
prompt = f"""Analyze this blog request...
Topic: {topic}
Target Audience: {audience}
Respond with a JSON object containing:
- "status": "CLEAR" if ready...
"""
```

**No prompt templates, no versioning, no A/B testing.**

### Workflow Engine

**None.** The pipeline is a simple sequential Python class:

```python
class BlogGenerationPipeline:
    async def run_full_pipeline(self, ...):
        intent = await self.run_intent_stage()
        outline = await self.run_outline_stage(intent)
        research = await self.run_research_stage(outline)
        final = await self.run_writing_stage(outline, research)
```

No state machine. No transitions. No rollback.

### Retry Handling

```python
# agents use google-adk retry config
retry_options=create_retry_config(attempts=3)
```

But at the pipeline level:
- No retry if agent fails
- Returns fallback/empty response
- No exponential backoff at orchestration layer

### Hallucination Detection

**NOT IMPLEMENTED**

```python
# pipeline.py:243-258
if response and len(response) > 200:
    # Just checks length, not content validity
    return {...}
```

No fact-checking, no source verification, no confidence scoring.

### Partial Failure Handling

```python
# pipeline.py:79-81
except Exception as e:
    logger.error("agent_run_failed", agent=agent.name, error=str(e))
    return ""  # ← Returns empty string, continues with fallback
```

If any agent fails, the pipeline uses hardcoded fallback content (not real AI-generated).

---

## 7. Error Handling & Resilience

### Retry Strategy

| Layer | Strategy |
|-------|----------|
| ADK Agent | 3 retries (built-in) |
| Pipeline | No retries (fails silently) |
| Repository | No retries |
| HTTP Routes | No retries |

### Timeout Handling

**No explicit timeouts.** Relies on:
- Uvicorn worker timeout (not configured)
- ADK/gRPC defaults (unknown)

Cloud Run would timeout at 300s (configured in deploy script).

### Circuit Breakers

```python
# circuit_breaker.py
class CircuitBreaker:
    failure_threshold = 5
    recovery_timeout = 60  # seconds
```

**Implemented for:**
- `gemini_circuit_breaker`
- `tavily_circuit_breaker`

**BUT:** Circuit breakers are defined but **not used in the pipeline**. The `_run_agent` method doesn't wrap calls in circuit breakers.

```python
# pipeline.py:46-81 - No circuit breaker usage
async def _run_agent(self, agent: Agent, prompt: str):
    # Direct call, no circuit breaker
    async for event in runner.run_async(...):
        ...
```

### Failure Scenarios

| Scenario | Behavior |
|----------|----------|
| LLM is slow | Request blocks indefinitely |
| LLM fails | Returns fallback content, no error to user |
| Database is down | 500 error during startup checks |
| Redis is down | Rate limiting fails open (allows all) |
| Tavily fails | Research returns empty sources |

---

## 8. Concurrency & Scaling Model

### Horizontal Scalability

**CANNOT SCALE HORIZONTALLY** due to:

```python
# pipeline.py:44
self._session_service = InMemorySessionService()
```

ADK sessions are stored in-memory. Multi-instance deployment breaks HITL workflow.

### In-Memory State

| State | Scope | Impact |
|-------|-------|--------|
| `InMemorySessionService` | Per-instance | Breaks multi-pod |
| `request_semaphore` | Per-instance | OK (per-pod limiting) |
| Circuit breaker state | Per-instance | OK (each pod tracks independently) |

### Concurrent Blog Generations

```python
# middleware.py:200
app.add_middleware(ConcurrencyLimitMiddleware, max_concurrent=config.max_concurrent_requests)
```

Concurrency is limited by semaphore (default: 5-50 based on env). But all concurrent requests share the single uvicorn worker process.

### Race Conditions

**Possible:**
1. Two requests updating the same blog's `stage_data` simultaneously
2. Rate limit counter increments (Redis INCR is atomic, but check-then-increment is not)
3. User creation (no unique constraint violation handling)

---

## 9. Background Processing

### Background Jobs/Queues

**NONE IMPLEMENTED**

All blog generation runs synchronously in the HTTP request handler.

### Long-Running Generation Handling

```python
# 60-second blog generation blocks the HTTP worker
result = await self.pipeline.run_full_pipeline(...)
```

No job queue. No async task offloading. No WebSocket for progress.

### Request Timeout

- **Uvicorn:** No explicit timeout configured
- **Cloud Run:** 300s (in deploy script)
- **Client:** Likely 30-60s browser timeout

**Risk:** Client timeout before generation completes = orphaned in-progress blog.

---

## 10. Observability

### Logging Strategy

```python
from src.config.logging_config import get_logger
logger = get_logger(__name__)

logger.info("blog_session_created", user_id=user_id, session_id=session_id)
```

**Structured logging with structlog:**
- JSON format
- Includes request_id
- Logged to stdout

### Metrics Collected

```python
# metrics.py
http_requests_total         # Counter by method/endpoint/status
http_request_duration_seconds  # Histogram
blog_generations_total      # Counter by status
agent_invocations_total     # Counter by agent/success
agent_token_usage           # Histogram
agent_cost_usd              # Histogram
rate_limit_rejections_total # Counter
circuit_breaker_state       # Gauge
```

**Exposed at:** `/metrics` (Prometheus format)

### Tracing Support

**NOT IMPLEMENTED**

No OpenTelemetry. No distributed tracing. No span propagation.

### Production Debugging

Available tools:
1. Structured logs with request_id correlation
2. Prometheus metrics
3. Health check dependency status

Missing:
- Distributed tracing
- Error tracking (Sentry)
- Log aggregation (Datadog configured but not integrated)

---

## 11. Security Posture

### Input Validation

```python
# Pydantic validation
topic: str = Field(..., min_length=10, max_length=500)
audience: str | None = Field(None, max_length=200)
```

```python
# sanitization.py - LLM prompt injection protection
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"you\s+are\s+now\s+(a|an)",
    ...
]
```

**Sanitization defined but NOT CALLED in request handlers.**

### Injection Protections

- **SQL Injection:** Protected by SQLAlchemy ORM
- **Prompt Injection:** Defined but not enforced
- **XSS:** N/A (API only, no HTML rendering)

### Secret Management

| Secret | Storage | Rotation |
|--------|---------|----------|
| GOOGLE_API_KEY | Environment variable | Manual |
| TAVILY_API_KEY | Environment variable | Manual |
| DATABASE_URL | Environment variable | Manual |

**Kubernetes secrets template exists but manual management in production.**

### Data Exposure

**Logs:**
- Topic and audience logged (could be PII)
- User IDs logged
- Full content NOT logged

**LLM:**
- User topic sent to Gemini (Google data retention applies)
- User topic sent to Tavily (3rd party)

---

## 12. Deployment Architecture

### Container

```dockerfile
# Multi-stage build
FROM python:3.10-slim as builder
FROM python:3.10-slim as production
USER appuser  # Non-root
HEALTHCHECK --interval=30s CMD python -c "..."
```

### Orchestration

**Kubernetes (GKE) or Cloud Run**

```yaml
# kubernetes/deployment.yaml
replicas: 2
resources:
  requests: 512Mi / 250m
  limits: 1Gi / 500m
HorizontalPodAutoscaler:
  min: 2, max: 10
  target CPU: 70%
```

### Environment Separation

| Environment | Config File | Key Differences |
|-------------|-------------|-----------------|
| dev | .env.dev | DEBUG logs, localhost CORS |
| stage | .env.stage | INFO logs, Datadog enabled |
| prod | .env.prod | WARNING logs, strict CORS |

### Config Management

Pydantic Settings loading from environment files:

```python
class DevelopmentConfig(BaseConfig):
    model_config = SettingsConfigDict(env_file=".env.dev")
```

### Secrets Handling

```yaml
# kubernetes/secrets.yaml.template
stringData:
  google-api-key: "REPLACE_ME"
```

Current: Manual replacement  
Recommended: Google Secret Manager integration

---

## 13. Failure Modes

### Critical Failures That Will Break Production

1. **InMemorySessionService**
   - **Impact:** HITL workflow fails across replicas
   - **Trigger:** Any multi-pod deployment
   - **Fix Required:** Replace with Redis-backed session store

2. **No Request Timeouts**
   - **Impact:** Worker exhaustion during Gemini outage
   - **Trigger:** Gemini API slowdown
   - **Fix Required:** Add explicit timeouts (30-60s)

3. **Synchronous LLM Calls in HTTP Handler**
   - **Impact:** All workers blocked during generation
   - **Trigger:** 5 concurrent blog requests
   - **Fix Required:** Async task queue (Celery/Cloud Tasks)

4. **Missing Authentication**
   - **Impact:** Any client can impersonate any user
   - **Trigger:** Intentional abuse
   - **Fix Required:** External auth integration

5. **No Idempotency**
   - **Impact:** Duplicate blogs on retry
   - **Trigger:** Client retry after timeout
   - **Fix Required:** Idempotency keys

6. **Unused Sanitization**
   - **Impact:** Prompt injection possible
   - **Trigger:** Malicious topic input
   - **Fix Required:** Call sanitize_topic() in handlers

7. **Circuit Breakers Not Wired**
   - **Impact:** Cascade failures during Gemini outage
   - **Trigger:** Gemini rate limiting
   - **Fix Required:** Wrap agent calls in circuit breaker

---

## 14. Production Readiness Assessment

### Verdict: ADVANCED PROTOTYPE - NOT PRODUCTION READY

### Justification

**Ready:**
- ✅ Clean architecture (routes → controllers → services)
- ✅ Database migrations exist
- ✅ Prometheus metrics exported
- ✅ Health checks with dependency verification
- ✅ Graceful shutdown implemented
- ✅ Kubernetes manifests exist
- ✅ CI/CD pipeline defined
- ✅ Rate limiting implemented
- ✅ Structured logging

**Not Ready:**

| Issue | Severity | Production Impact |
|-------|----------|-------------------|
| No authentication | CRITICAL | Any client can abuse API |
| InMemorySessionService | CRITICAL | Cannot scale horizontally |
| Synchronous LLM blocking | HIGH | Worker exhaustion |
| No timeouts | HIGH | Hung requests |
| Unused circuit breakers | HIGH | Cascade failures |
| No distributed tracing | MEDIUM | Debugging difficult |
| No idempotency | MEDIUM | Duplicate generation |
| No background queue | MEDIUM | Client timeouts |
| Sanitization not called | MEDIUM | Prompt injection risk |

### Minimum Changes for Production

1. Add external auth token validation
2. Replace `InMemorySessionService` with Redis
3. Add explicit request timeouts (30s)
4. Wire circuit breakers into pipeline
5. Call input sanitization in handlers
6. Add idempotency key support

### Recommended Timeline

| Phase | Effort | Deliverable |
|-------|--------|-------------|
| Week 1 | 3 days | Auth + Redis session |
| Week 2 | 2 days | Timeouts + Circuit breakers |
| Week 3 | 3 days | Background queue + Idempotency |
| Week 4 | 2 days | Load testing + Hardening |

**Estimated Production-Ready: 2-3 weeks**

---

## Appendix: File Inventory

| File | Lines | Purpose |
|------|-------|---------|
| `src/api/main.py` | 289 | FastAPI application |
| `src/api/routes/blog.py` | 131 | Blog endpoints |
| `src/api/middleware.py` | 261 | Request middleware |
| `src/services/blog_service.py` | 288 | Business logic |
| `src/agents/pipeline.py` | 320 | LLM orchestration |
| `src/models/repository.py` | 244 | Database operations |
| `src/models/orm_models.py` | 108 | SQLAlchemy models |
| `src/guards/rate_limit_guard.py` | 168 | Rate limiting |
| `src/monitoring/circuit_breaker.py` | 109 | Circuit breaker |
| `src/core/errors.py` | 296 | Error handling |
| `src/core/sanitization.py` | 181 | Input sanitization |
| **Total** | **~5,100** | |

---

*Report generated by automated codebase analysis. Findings reflect the actual implementation at commit e98743c.*
