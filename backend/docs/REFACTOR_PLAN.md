# Production Hardening Refactor Plan

**Document Type:** Implementation Blueprint  
**Date:** 2026-01-20  
**Status:** Ready for Implementation  
**Estimated Effort:** 5-7 days  

---

## Executive Summary

This document provides a concrete, file-by-file refactor plan to convert the current synchronous, stateful Blogify AI service into a production-grade, horizontally scalable, asynchronous architecture.

**Current State:**
- LLM calls block HTTP handlers (20-60s per request)
- InMemorySessionService replaced with Redis (✅ done)
- Workflow state partially in PostgreSQL
- No background workers

**Target State:**
- API returns 202 immediately after enqueueing
- Workers consume jobs and run LLM pipeline
- All state persisted in PostgreSQL
- Horizontally scalable

---

## 1. New Runtime Components

### Required Processes

| Process | Purpose | Scaling | Files |
|---------|---------|---------|-------|
| **API Server** | FastAPI - accepts requests, validates, enqueues | 2-10 pods | `src/api/*` |
| **Blog Worker** | Consumes queue, runs LLM pipeline | 1-5 pods | `src/workers/blog_worker.py` (new) |
| **Beat Scheduler** | Periodic tasks (cleanup, monitoring) | 1 pod | `src/workers/scheduler.py` (new) |

### Module Migration Map

| Current Module | Current Runtime | Target Runtime |
|----------------|-----------------|----------------|
| `src/api/routes/blog.py` | API | API (simplified) |
| `src/controllers/blog_controller.py` | API | API (validation only) |
| `src/services/blog_service.py` | API | **Worker** |
| `src/agents/pipeline.py` | API | **Worker** |
| `src/tools/tavily_research.py` | API | **Worker** |

---

## 2. Data Model Changes

### New Table: `blog_jobs`

```sql
CREATE TABLE blog_jobs (
    id SERIAL PRIMARY KEY,
    blog_id INTEGER NOT NULL REFERENCES blogs(id) ON DELETE CASCADE,
    session_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    
    -- Job State
    job_type VARCHAR(50) NOT NULL,           -- 'full_pipeline', 'stage_intent', 'stage_outline', etc.
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed, cancelled
    priority INTEGER DEFAULT 0,
    
    -- Input/Output
    input_data JSONB NOT NULL,
    output_data JSONB,
    error_message TEXT,
    
    -- Retry Tracking
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    last_attempt_at TIMESTAMP,
    next_retry_at TIMESTAMP,
    
    -- Lifecycle
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Worker Tracking
    worker_id VARCHAR(255),
    locked_until TIMESTAMP
);

CREATE INDEX idx_blog_jobs_status ON blog_jobs(status);
CREATE INDEX idx_blog_jobs_next_retry ON blog_jobs(next_retry_at) WHERE status = 'pending';
CREATE INDEX idx_blog_jobs_session ON blog_jobs(session_id);
```

### Schema Changes to `blogs` Table

```sql
-- Add columns (migration)
ALTER TABLE blogs ADD COLUMN job_id INTEGER REFERENCES blog_jobs(id);
ALTER TABLE blogs ADD COLUMN error_count INTEGER DEFAULT 0;
ALTER TABLE blogs ADD COLUMN last_error TEXT;
ALTER TABLE blogs ADD COLUMN worker_started_at TIMESTAMP;
ALTER TABLE blogs ADD COLUMN estimated_completion TIMESTAMP;
```

### Migration Order

1. **Phase 1:** Add `blog_jobs` table (non-breaking)
2. **Phase 2:** Add new columns to `blogs` table (non-breaking)
3. **Phase 3:** Deploy workers (parallel with API)
4. **Phase 4:** Switch API to enqueue (breaking change)

---

## 3. Queue Integration Plan

### Queue Library: Redis-Based Custom Queue

Use the existing `src/core/task_queue.py` with enhancements:

```python
# Queue names
QUEUE_BLOG_GENERATION = "blogify:queue:blog_generation"
QUEUE_STAGE_EXECUTION = "blogify:queue:stage_execution"
QUEUE_DEAD_LETTER = "blogify:queue:dead_letter"
```

### Enqueue Location

**File:** `src/api/routes/blog.py`

```python
# BEFORE (blocking)
result = await blog_controller.generate_blog_sync(...)
return BlogGenerationResponse(**result)

# AFTER (async)
job_id = await enqueue_blog_job(user_id, topic, audience)
return Response(status_code=202, content={"job_id": job_id, "status": "queued"})
```

### Worker Consumption

**File:** `src/workers/blog_worker.py` (new)

```python
async def run_worker():
    while True:
        job = await task_queue.dequeue(timeout=5)
        if job:
            await process_blog_job(job)
```

### Files to Modify

| File | Change |
|------|--------|
| `src/api/routes/blog.py` | Remove LLM calls, add enqueue |
| `src/controllers/blog_controller.py` | Remove service calls, add job creation |
| `src/core/task_queue.py` | Add job-specific methods |
| `src/models/repository.py` | Add blog_jobs CRUD |
| `src/models/orm_models.py` | Add BlogJob model |
| `src/workers/blog_worker.py` | New file - worker process |

---

## 4. Workflow Engine Refactor

### Current Implementation

```python
# src/services/blog_service.py:generate_blog_sync()
async def generate_blog_sync(self, user_id, topic, audience):
    await db_repository.create_blog(...)
    result = await self.pipeline.run_full_pipeline(...)  # BLOCKING 60s
    await db_repository.update_blog(...)
    return result
```

### Target: Persistent State Machine

```python
# State transitions stored in blogs.current_stage
STAGE_TRANSITIONS = {
    "pending": ["intent"],
    "intent": ["outline", "failed"],
    "outline": ["research", "failed"],
    "research": ["writing", "failed"],
    "writing": ["completed", "failed"],
    "completed": [],  # Terminal
    "failed": ["pending"],  # Can retry
}
```

### Stage Execution Flow

```python
# src/workers/stage_executor.py
class StageExecutor:
    async def execute_stage(self, blog_id: int, stage: str) -> str:
        """Execute a single stage, return next stage or 'failed'."""
        
        blog = await db_repository.get_blog(blog_id)
        
        try:
            if stage == "intent":
                result = await self.run_intent_stage(blog)
            elif stage == "outline":
                result = await self.run_outline_stage(blog)
            elif stage == "research":
                result = await self.run_research_stage(blog)
            elif stage == "writing":
                result = await self.run_writing_stage(blog)
            
            # Persist result
            await db_repository.update_blog_stage(
                blog.session_id,
                stage=stage,
                stage_data=result,
            )
            
            # Return next stage
            return STAGE_TRANSITIONS[stage][0]
            
        except Exception as e:
            await db_repository.update_blog_error(blog.session_id, str(e))
            return "failed"
```

### Retry Handling Per Stage

```python
# src/workers/blog_worker.py
async def process_blog_job(job: dict):
    blog_id = job["payload"]["blog_id"]
    current_stage = job["payload"]["stage"]
    
    try:
        next_stage = await stage_executor.execute_stage(blog_id, current_stage)
        
        if next_stage == "completed":
            await task_queue.update_task(job["id"], status=TaskStatus.COMPLETED)
        elif next_stage == "failed":
            if job["attempts"] < job["max_attempts"]:
                # Retry with exponential backoff
                await task_queue.requeue_with_backoff(job["id"])
            else:
                await task_queue.move_to_dead_letter(job["id"])
        else:
            # Enqueue next stage
            await enqueue_stage_job(blog_id, next_stage)
            await task_queue.update_task(job["id"], status=TaskStatus.COMPLETED)
            
    except Exception as e:
        logger.error("job_failed", job_id=job["id"], error=str(e))
        await task_queue.requeue_with_backoff(job["id"])
```

---

## 5. Authentication Refactor

### JWT Validation Middleware

**File:** `src/api/middleware.py` (add)

```python
from fastapi import Request, HTTPException
from jose import jwt, JWTError

class AuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT tokens from external auth service."""
    
    # Routes that don't require auth
    PUBLIC_ROUTES = {"/health", "/docs", "/openapi.json", "/metrics"}
    
    async def dispatch(self, request: Request, call_next):
        # Skip public routes
        if any(request.url.path.startswith(r) for r in self.PUBLIC_ROUTES):
            return await call_next(request)
        
        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(401, "Missing authorization token")
        
        token = auth_header.split(" ")[1]
        
        try:
            # Validate with external auth service's public key
            payload = jwt.decode(
                token,
                config.jwt_public_key,
                algorithms=["RS256"],
                audience=config.jwt_audience,
            )
            
            # Attach user to request state
            request.state.user_id = payload.get("sub")
            request.state.user_email = payload.get("email")
            request.state.token_claims = payload
            
        except JWTError as e:
            raise HTTPException(401, f"Invalid token: {str(e)}")
        
        return await call_next(request)
```

### Route Changes

**File:** `src/api/routes/blog.py`

```python
# BEFORE
class BlogGenerationRequest(BaseModel):
    user_id: str  # Client-provided (INSECURE)
    topic: str
    ...

@router.post("/blog/generate")
async def generate_blog(request: BlogGenerationRequest):
    result = await blog_controller.initiate_blog_generation(
        user_id=request.user_id,  # From request body
        ...
    )

# AFTER
class BlogGenerationRequest(BaseModel):
    # user_id REMOVED - extracted from JWT
    topic: str
    ...

@router.post("/blog/generate")
async def generate_blog(
    request: BlogGenerationRequest,
    req: Request,  # FastAPI request for state
):
    user_id = req.state.user_id  # From JWT (SECURE)
    
    result = await blog_controller.initiate_blog_generation(
        user_id=user_id,
        ...
    )
```

### Config Changes

**File:** `src/config/env_config.py`

```python
class BaseConfig(BaseSettings):
    # Add JWT config
    jwt_public_key: str = ""
    jwt_audience: str = "blogify-api"
    jwt_issuer: str = ""
```

---

## 6. File-by-File Refactor Map

### API Layer Files

| File | Action | Details |
|------|--------|---------|
| `src/api/routes/blog.py` | **MAJOR REFACTOR** | Remove all `await controller.generate_*()` calls. Replace with job enqueueing. Add 202 responses. Remove `user_id` from request body. |
| `src/api/middleware.py` | **ADD AUTH** | Add `AuthMiddleware` class for JWT validation. Add to `setup_middleware()`. |
| `src/api/main.py` | **MINOR UPDATE** | Add auth middleware. Import worker health endpoint. |

### Controller Layer

| File | Action | Details |
|------|--------|---------|
| `src/controllers/blog_controller.py` | **SIMPLIFY** | Remove all `await self.service.*()` calls. Replace `initiate_blog_generation()` with `create_and_enqueue_job()`. Keep validation logic. |

### Service Layer

| File | Action | Details |
|------|--------|---------|
| `src/services/blog_service.py` | **MOVE TO WORKER** | All `run_*_stage()` calls move to worker. Keep only DB operations that API needs. |

### Pipeline Layer

| File | Action | Details |
|------|--------|---------|
| `src/agents/pipeline.py` | **SPLIT** | Break `run_full_pipeline()` into individual stage methods. Each stage is independently callable. Remove `run_full_pipeline()` entirely. |

### Model Layer

| File | Action | Details |
|------|--------|---------|
| `src/models/orm_models.py` | **ADD MODEL** | Add `BlogJob` ORM model. Add new columns to `Blog` model. |
| `src/models/repository.py` | **ADD METHODS** | Add `create_blog_job()`, `get_pending_jobs()`, `update_job_status()`, `claim_job()`, `release_job()`. |

### New Worker Files

| File | Purpose | Contents |
|------|---------|----------|
| `src/workers/__init__.py` | Package init | Imports |
| `src/workers/blog_worker.py` | Main worker loop | `run_worker()`, `process_blog_job()` |
| `src/workers/stage_executor.py` | Stage execution | `StageExecutor` class with per-stage methods |
| `src/workers/scheduler.py` | Periodic tasks | Cleanup, retry scheduling, metrics |

### Core Layer Updates

| File | Action | Details |
|------|--------|---------|
| `src/core/task_queue.py` | **ENHANCE** | Add `claim_job()`, `release_job()`, `requeue_with_backoff()`, `move_to_dead_letter()`. |
| `src/core/job_enqueue.py` | **NEW FILE** | `enqueue_blog_job()`, `enqueue_stage_job()` helper functions. |

---

## 7. Detailed File Changes

### `src/api/routes/blog.py` (REFACTORED)

```python
"""Blog generation API routes - accepts requests, enqueues jobs."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger
from src.core.idempotency import idempotency_store
from src.core.job_enqueue import enqueue_blog_job
from src.models.repository import db_repository

logger = get_logger(__name__)
router = APIRouter()


class BlogGenerationRequest(BaseModel):
    """Blog generation request - user_id from JWT."""
    # user_id: REMOVED - extracted from JWT token
    topic: str = Field(..., min_length=10, max_length=500)
    audience: str | None = Field(None, max_length=200)


class BlogGenerationResponse(BaseModel):
    """202 Accepted response."""
    session_id: str
    job_id: str
    status: str = "queued"
    message: str
    poll_url: str


@router.post("/blog/generate", status_code=202, response_model=BlogGenerationResponse)
async def generate_blog(
    request: BlogGenerationRequest,
    req: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """
    Initiate blog generation (async).
    
    Returns 202 immediately. Poll /blog/job/{job_id} for status.
    """
    # Get user from JWT (set by AuthMiddleware)
    user_id = req.state.user_id
    
    # Idempotency check
    is_new, cached = await idempotency_store.check_and_set(
        user_id=user_id,
        endpoint="/blog/generate",
        idempotency_key=idempotency_key,
        request_body=request.model_dump(),
    )
    
    if not is_new and cached:
        return BlogGenerationResponse(**cached)
    
    # Create blog record in DB
    blog = await db_repository.create_blog(
        user_id=user_id,
        session_id=str(uuid.uuid4()),
        topic=request.topic,
        audience=request.audience,
    )
    
    # Enqueue job (NO LLM CALLS HERE)
    job_id = await enqueue_blog_job(
        blog_id=blog.id,
        session_id=blog.session_id,
        user_id=user_id,
        topic=request.topic,
        audience=request.audience,
    )
    
    response = BlogGenerationResponse(
        session_id=blog.session_id,
        job_id=job_id,
        status="queued",
        message="Blog generation queued. Poll for status.",
        poll_url=f"/api/v1/blog/job/{job_id}",
    )
    
    # Cache for idempotency
    await idempotency_store.set_response(
        user_id=user_id,
        endpoint="/blog/generate",
        response=response.model_dump(),
        idempotency_key=idempotency_key,
    )
    
    return response


@router.get("/blog/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status for polling."""
    job = await db_repository.get_blog_job(job_id)
    
    if not job:
        raise HTTPException(404, "Job not found")
    
    return {
        "job_id": job_id,
        "status": job.status,
        "current_stage": job.current_stage,
        "progress": calculate_progress(job.current_stage),
        "result": job.output_data if job.status == "completed" else None,
        "error": job.error_message if job.status == "failed" else None,
    }
```

### `src/workers/blog_worker.py` (NEW)

```python
"""Background worker for blog generation jobs."""

import asyncio
import signal
import sys
from datetime import datetime

from src.config.logging_config import get_logger, setup_logging
from src.core.task_queue import task_queue, TaskStatus
from src.models.repository import db_repository
from src.workers.stage_executor import StageExecutor

setup_logging("INFO")
logger = get_logger(__name__)

# Worker configuration
POLL_INTERVAL = 1  # seconds
SHUTDOWN_TIMEOUT = 30

# Shutdown flag
shutdown_requested = False


async def run_worker(worker_id: str):
    """Main worker loop."""
    global shutdown_requested
    
    logger.info("worker_started", worker_id=worker_id)
    
    executor = StageExecutor()
    
    while not shutdown_requested:
        try:
            # Try to claim a job
            job = await task_queue.dequeue(timeout=POLL_INTERVAL)
            
            if job is None:
                continue
            
            logger.info("job_claimed", job_id=job["id"], worker_id=worker_id)
            
            # Process the job
            await process_blog_job(job, executor, worker_id)
            
        except Exception as e:
            logger.error("worker_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)
    
    logger.info("worker_shutdown", worker_id=worker_id)


async def process_blog_job(job: dict, executor: StageExecutor, worker_id: str):
    """Process a single blog generation job."""
    job_id = job["id"]
    blog_id = job["payload"]["blog_id"]
    current_stage = job["payload"].get("stage", "intent")
    
    try:
        # Update job status
        await task_queue.update_task(job_id, status=TaskStatus.PROCESSING)
        await db_repository.update_blog_job(job_id, worker_id=worker_id, started_at=datetime.utcnow())
        
        # Execute the stage
        logger.info("executing_stage", job_id=job_id, stage=current_stage)
        
        result, next_stage = await executor.execute_stage(blog_id, current_stage)
        
        if next_stage == "completed":
            # All done
            await task_queue.update_task(job_id, status=TaskStatus.COMPLETED, result=result)
            await db_repository.update_blog(blog_id, status="completed")
            logger.info("job_completed", job_id=job_id)
            
        elif next_stage == "failed":
            # Handle failure
            await handle_job_failure(job, result.get("error", "Unknown error"))
            
        else:
            # Enqueue next stage
            await enqueue_next_stage(blog_id, next_stage, job["payload"])
            await task_queue.update_task(job_id, status=TaskStatus.COMPLETED)
            logger.info("stage_completed", job_id=job_id, next_stage=next_stage)
            
    except Exception as e:
        logger.error("job_failed", job_id=job_id, error=str(e))
        await handle_job_failure(job, str(e))


async def handle_job_failure(job: dict, error: str):
    """Handle job failure with retry logic."""
    job_id = job["id"]
    attempts = job.get("attempts", 0) + 1
    max_attempts = job.get("max_attempts", 3)
    
    if attempts < max_attempts:
        # Retry with exponential backoff
        backoff = min(300, 2 ** attempts * 10)  # Max 5 minutes
        logger.info("job_retry_scheduled", job_id=job_id, attempt=attempts, backoff=backoff)
        await task_queue.requeue(job_id)
    else:
        # Move to dead letter queue
        logger.error("job_max_retries", job_id=job_id)
        await task_queue.update_task(job_id, status=TaskStatus.FAILED, error=error)


async def enqueue_next_stage(blog_id: int, stage: str, original_payload: dict):
    """Enqueue the next stage for processing."""
    payload = {**original_payload, "stage": stage}
    await task_queue.enqueue(
        task_type="blog_stage",
        payload=payload,
    )


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    logger.info("shutdown_signal_received", signal=signum)
    shutdown_requested = True


def main():
    """Entry point for worker process."""
    import uuid
    
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run worker
    asyncio.run(run_worker(worker_id))


if __name__ == "__main__":
    main()
```

### `src/workers/stage_executor.py` (NEW)

```python
"""Stage executor - runs individual pipeline stages."""

from typing import Any, Tuple

from src.agents.pipeline import BlogGenerationPipeline
from src.config.logging_config import get_logger
from src.models.repository import db_repository

logger = get_logger(__name__)


class StageExecutor:
    """Executes individual pipeline stages."""
    
    def __init__(self):
        self.pipeline = BlogGenerationPipeline()
    
    async def execute_stage(
        self, blog_id: int, stage: str
    ) -> Tuple[dict[str, Any], str]:
        """
        Execute a single stage.
        
        Returns:
            (result_data, next_stage)
            next_stage can be: 'outline', 'research', 'writing', 'completed', 'failed'
        """
        blog = await db_repository.get_blog(blog_id)
        
        if not blog:
            return {"error": "Blog not found"}, "failed"
        
        try:
            if stage == "intent":
                return await self._run_intent(blog)
            elif stage == "outline":
                return await self._run_outline(blog)
            elif stage == "research":
                return await self._run_research(blog)
            elif stage == "writing":
                return await self._run_writing(blog)
            else:
                return {"error": f"Unknown stage: {stage}"}, "failed"
                
        except Exception as e:
            logger.error("stage_execution_failed", stage=stage, error=str(e))
            return {"error": str(e)}, "failed"
    
    async def _run_intent(self, blog) -> Tuple[dict, str]:
        """Run intent clarification stage."""
        result = await self.pipeline.run_intent_stage(
            topic=blog.topic,
            audience=blog.audience or "general readers",
        )
        
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="intent",
            stage_data=result,
        )
        
        if result.get("status") == "INVALID_INPUT":
            return result, "failed"
        
        return result, "outline"
    
    async def _run_outline(self, blog) -> Tuple[dict, str]:
        """Run outline generation stage."""
        intent_data = blog.stage_data or {}
        
        result = await self.pipeline.run_outline_stage(intent_data)
        
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="outline",
            stage_data=result,
        )
        
        return result, "research"
    
    async def _run_research(self, blog) -> Tuple[dict, str]:
        """Run research stage."""
        outline_data = blog.stage_data or {}
        
        result = await self.pipeline.run_research_stage(outline_data)
        
        await db_repository.update_blog_stage(
            session_id=blog.session_id,
            stage="research",
            stage_data=result,
        )
        
        return result, "writing"
    
    async def _run_writing(self, blog) -> Tuple[dict, str]:
        """Run writing stage - final stage."""
        # Get accumulated data
        outline = blog.stage_data or {}
        
        # Fetch research data (stored in previous job)
        research_data = await db_repository.get_stage_data(blog.session_id, "research")
        
        result = await self.pipeline.run_writing_stage(outline, research_data)
        
        # Update blog with final content
        await db_repository.update_blog(
            session_id=blog.session_id,
            title=result.get("title"),
            content=result.get("content"),
            word_count=result.get("word_count", 0),
            sources_count=result.get("sources_count", 0),
            status="completed",
        )
        
        return result, "completed"
```

---

## 8. Backward-Compatible Migration Plan

### Phase 1: Database Preparation (Day 1)
- Add `blog_jobs` table via Alembic migration
- Add new columns to `blogs` table
- **No application changes - fully backward compatible**

### Phase 2: Deploy Workers (Day 2)
- Deploy `blog_worker.py` as separate process
- Configure Kubernetes Deployment for workers
- Workers idle (no jobs yet)
- **API unchanged - still synchronous**

### Phase 3: Dual-Mode API (Day 3)
- Add `async_mode=true` parameter to `/blog/generate`
- When `async_mode=true`, enqueue to workers
- When `async_mode=false` (default), run synchronously
- **Backward compatible - existing clients work**

### Phase 4: Client Migration (Day 4-5)
- Notify clients of new async mode
- Update documentation
- Monitor async vs sync usage

### Phase 5: Sunset Sync Mode (Day 6-7)
- Set `async_mode=true` as default
- Deprecation warning for sync mode
- Eventually remove sync mode

### Existing In-Progress Blogs

```python
# Migration script for in-progress blogs
async def migrate_in_progress_blogs():
    """Convert in-progress blogs to job queue."""
    
    blogs = await db_repository.get_blogs_by_status("in_progress")
    
    for blog in blogs:
        # Create job from current state
        job_id = await enqueue_blog_job(
            blog_id=blog.id,
            session_id=blog.session_id,
            user_id=blog.user_id,
            topic=blog.topic,
            audience=blog.audience,
            stage=blog.current_stage or "intent",
        )
        
        logger.info("migrated_blog", blog_id=blog.id, job_id=job_id)
```

---

## 9. Final Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PRODUCTION ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────┐
                              │   Load Balancer │
                              │    (Nginx/K8s)  │
                              └────────┬────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 │                     │                     │
                 ▼                     ▼                     ▼
        ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
        │   API Pod 1    │    │   API Pod 2    │    │   API Pod N    │
        │                │    │                │    │                │
        │ ┌────────────┐ │    │ ┌────────────┐ │    │ ┌────────────┐ │
        │ │  FastAPI   │ │    │ │  FastAPI   │ │    │ │  FastAPI   │ │
        │ │            │ │    │ │            │ │    │ │            │ │
        │ │ - Auth     │ │    │ │ - Auth     │ │    │ │ - Auth     │ │
        │ │ - Validate │ │    │ │ - Validate │ │    │ │ - Validate │ │
        │ │ - Enqueue  │ │    │ │ - Enqueue  │ │    │ │ - Enqueue  │ │
        │ └────────────┘ │    │ └────────────┘ │    │ └────────────┘ │
        └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
                │                     │                     │
                └─────────────────────┼─────────────────────┘
                                      │
                     ┌────────────────┼────────────────┐
                     │                │                │
                     ▼                ▼                ▼
              ┌───────────┐    ┌───────────┐    ┌───────────┐
              │  Redis    │    │ PostgreSQL│    │ External  │
              │           │    │           │    │ Auth Svc  │
              │ - Queue   │    │ - blogs   │    │           │
              │ - Session │    │ - jobs    │    │ - JWT     │
              │ - Rate    │    │ - costs   │    │           │
              └─────┬─────┘    └───────────┘    └───────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌────────────────┐     ┌────────────────┐
│  Worker Pod 1  │     │  Worker Pod N  │
│                │     │                │
│ ┌────────────┐ │     │ ┌────────────┐ │
│ │ Stage      │ │     │ │ Stage      │ │
│ │ Executor   │ │     │ │ Executor   │ │
│ │            │ │     │ │            │ │
│ │ - Intent   │ │     │ │ - Intent   │ │
│ │ - Outline  │ │     │ │ - Outline  │ │
│ │ - Research │ │     │ │ - Research │ │
│ │ - Writing  │ │     │ │ - Writing  │ │
│ └─────┬──────┘ │     │ └─────┬──────┘ │
│       │        │     │       │        │
│       ▼        │     │       ▼        │
│ ┌───────────┐  │     │ ┌───────────┐  │
│ │ Gemini API│  │     │ │ Gemini API│  │
│ └───────────┘  │     │ └───────────┘  │
│ ┌───────────┐  │     │ ┌───────────┐  │
│ │Tavily API │  │     │ │Tavily API │  │
│ └───────────┘  │     │ └───────────┘  │
└────────────────┘     └────────────────┘


Request Flow:
═══════════════════════════════════════════════════════════════════════════════

1. Client → API: POST /blog/generate
2. API: Validate JWT ✓ → Validate Input ✓ → Create Blog in DB → Enqueue Job
3. API → Client: 202 Accepted {job_id, poll_url}

4. Worker: Dequeue Job → Execute Stage → Update DB → Enqueue Next Stage
5. Worker: (repeat until completed)

6. Client → API: GET /blog/job/{id}
7. API → Client: {status: completed, result: {...}}
```

---

## 10. Test Fixes

### Fix Mocking Paths

The tests fail because patch targets are incorrect. Update:

**File:** `tests/unit/test_service.py`

```python
# WRONG - patching on the import target
with patch("src.services.blog_service.db_repository") as mock_repo:

# CORRECT - patch where it's used
with patch("src.models.repository.db_repository") as mock_repo:
```

**File:** `tests/integration/test_hitl.py`

```python
# WRONG
with patch("src.services.blog_service.blog_pipeline") as mock_pipeline:

# CORRECT  
with patch("src.agents.pipeline.blog_pipeline") as mock_pipeline:
```

---

## 11. Kubernetes Deployments

### Worker Deployment

```yaml
# kubernetes/worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blogify-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: blogify-worker
  template:
    metadata:
      labels:
        app: blogify-worker
    spec:
      containers:
        - name: worker
          image: gcr.io/PROJECT/blogify-api:latest
          command: ["python", "-m", "src.workers.blog_worker"]
          env:
            - name: WORKER_MODE
              value: "true"
          resources:
            requests:
              memory: "1Gi"
              cpu: "500m"
            limits:
              memory: "2Gi"
              cpu: "1000m"
```

---

## Summary Checklist

| Task | Files | Effort |
|------|-------|--------|
| Add `blog_jobs` table | `orm_models.py`, migration | 2h |
| Create worker process | `workers/blog_worker.py` | 4h |
| Create stage executor | `workers/stage_executor.py` | 3h |
| Refactor API routes | `routes/blog.py` | 3h |
| Add auth middleware | `middleware.py` | 2h |
| Add job enqueueing | `core/job_enqueue.py` | 2h |
| Repository updates | `repository.py` | 2h |
| Fix tests | `tests/**` | 2h |
| K8s deployments | `kubernetes/` | 2h |
| Documentation | `docs/` | 1h |
| **Total** | | **~23h (3 days)** |

---

*This refactor plan is designed for incremental implementation without breaking the existing system.*
