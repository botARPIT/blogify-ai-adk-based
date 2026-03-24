# Production Backpressure & Circuit Breaking Implementation

**Date:** 2026-01-20  
**Author:** Principal Distributed Systems Engineer  
**Status:** Implementation Ready  

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PRESSURE CONTROL ARCHITECTURE                             │
└─────────────────────────────────────────────────────────────────────────────┘

Client
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BLOGIFY API (Upstream)                               │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────────────────┐    │
│  │ Rate Limit  │──▶│ Semaphore   │──▶│ Circuit Breaker → Blogify-AI   │    │
│  │ (per user)  │   │ MAX=50      │   │ (50% fail → open)              │    │
│  └─────────────┘   └─────────────┘   └─────────────────────────────────┘    │
└────────────────────────────────────────────┬────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BLOGIFY-AI API (This Service)                          │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐     │
│  │ JWT Validate│──▶│ Rate Limit  │──▶│ Concurrency │──▶│ Queue Check │     │
│  │             │   │ (per user)  │   │ Semaphore   │   │ (depth < N) │     │
│  └─────────────┘   └─────────────┘   │ MAX=100     │   └─────────────┘     │
│                                      └─────────────┘                        │
└────────────────────────────────────────────┬────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REDIS QUEUE                                        │
│              MAX_DEPTH=1000 │ Reject when full (503)                        │
└────────────────────────────────────────────┬────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BLOGIFY-AI WORKERS                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Job Semaphore (MAX_CONCURRENT_JOBS=3 per worker)                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                             │                                │
│      ┌──────────────────┬──────────────────┼─────────────────────┐          │
│      ▼                  ▼                  ▼                     ▼          │
│  ┌────────┐        ┌────────┐        ┌──────────┐         ┌───────────┐    │
│  │Gemini  │        │Tavily  │        │PostgreSQL│         │   Redis   │    │
│  │Circuit │        │Circuit │        │Pool Limit│         │Pool Limit │    │
│  │Breaker │        │Breaker │        │ timeout  │         │ timeout   │    │
│  │+30s TO │        │+15s TO │        │   3s     │         │   2s      │    │
│  └────────┘        └────────┘        └──────────┘         └───────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. API Layer Protection (src/api/)

### File: src/core/backpressure.py (NEW)

```python
"""Backpressure controls for API layer."""

import asyncio
import time
from typing import Any
from dataclasses import dataclass
from enum import Enum

from src.config.logging_config import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitStats:
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0
    state: CircuitState = CircuitState.CLOSED


class CircuitBreaker:
    """
    Circuit breaker with rolling window failure detection.
    
    Config:
    - failure_threshold: % failures to trip (e.g., 0.5 = 50%)
    - window_size: Rolling window in seconds
    - recovery_timeout: Seconds before half-open attempt
    - min_calls: Minimum calls before evaluating threshold
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        window_size: int = 30,
        recovery_timeout: int = 30,
        min_calls: int = 10,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_size = window_size
        self.recovery_timeout = recovery_timeout
        self.min_calls = min_calls
        
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._successes = 0
        self._last_failure_time = 0
        self._window_start = time.time()
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    async def call(self, func, *args, **kwargs) -> Any:
        """Execute function through circuit breaker."""
        async with self._lock:
            self._maybe_reset_window()
            
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(f"circuit_half_open", name=self.name)
                else:
                    raise CircuitOpenError(f"{self.name} circuit is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure()
            raise
    
    async def _record_success(self):
        async with self._lock:
            self._successes += 1
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failures = 0
                logger.info("circuit_closed", name=self.name)
    
    async def _record_failure(self):
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            
            total = self._failures + self._successes
            if total >= self.min_calls:
                failure_rate = self._failures / total
                if failure_rate >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "circuit_opened",
                        name=self.name,
                        failure_rate=failure_rate,
                    )
    
    def _maybe_reset_window(self):
        if time.time() - self._window_start > self.window_size:
            self._failures = 0
            self._successes = 0
            self._window_start = time.time()


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class ConcurrencyLimiter:
    """
    Semaphore-based concurrency limiter with timeout.
    """
    
    def __init__(self, name: str, max_concurrent: int, acquire_timeout: float = 5.0):
        self.name = name
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """Acquire slot with timeout. Returns False if timeout."""
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.acquire_timeout,
            )
            async with self._lock:
                self._current += 1
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "concurrency_limit_timeout",
                name=self.name,
                current=self._current,
                max=self.max_concurrent,
            )
            return False
    
    def release(self):
        """Release slot."""
        self._semaphore.release()
        # Note: _current decrement not strictly needed for semaphore
    
    @property
    def available(self) -> int:
        return self._semaphore._value
    
    async def __aenter__(self):
        acquired = await self.acquire()
        if not acquired:
            raise ConcurrencyLimitExceeded(
                f"{self.name}: concurrency limit reached ({self.max_concurrent})"
            )
        return self
    
    async def __aexit__(self, *args):
        self.release()


class ConcurrencyLimitExceeded(Exception):
    """Raised when concurrency limit is exceeded."""
    pass


# Global instances for API layer
api_concurrency_limiter = ConcurrencyLimiter(
    name="api_ingress",
    max_concurrent=100,  # API can handle more since it just enqueues
    acquire_timeout=5.0,
)

# Queue depth limiter
MAX_QUEUE_DEPTH = 1000
```

---

## 2. Queue Level Pressure Control

### File: src/core/task_queue.py (UPDATES)

Add to existing TaskQueue class:

```python
class TaskQueue:
    # ... existing code ...
    
    MAX_QUEUE_DEPTH = 1000  # Maximum pending jobs
    
    async def enqueue(self, task_type: str, payload: dict, ...) -> str:
        """Enqueue with depth check - reject if queue too deep."""
        client = await self._get_client()
        
        # Check queue depth before enqueue
        current_depth = await client.llen(self.QUEUE_NAME)
        if current_depth >= self.MAX_QUEUE_DEPTH:
            logger.warning(
                "queue_depth_exceeded",
                current=current_depth,
                max=self.MAX_QUEUE_DEPTH,
            )
            raise QueueFullError(
                f"Queue depth {current_depth} exceeds maximum {self.MAX_QUEUE_DEPTH}"
            )
        
        # ... rest of enqueue logic ...


class QueueFullError(Exception):
    """Raised when queue depth exceeds maximum."""
    pass
```

---

## 3. Worker Level Concurrency Control

### File: src/workers/blog_worker.py (UPDATES)

```python
# Worker-level concurrency (limits CPU/memory per worker)
MAX_CONCURRENT_JOBS = 3  # Per worker instance
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


async def run_worker(worker_id: str | None = None):
    # ... existing setup ...
    
    while not shutdown_requested:
        # Only claim if we have capacity
        if job_semaphore.locked() and job_semaphore._value == 0:
            await asyncio.sleep(0.1)
            continue
        
        job = await task_queue.dequeue(timeout=POLL_INTERVAL)
        if job:
            # Process with semaphore protection
            asyncio.create_task(process_with_semaphore(job, executor, worker_id))


async def process_with_semaphore(job: dict, executor: StageExecutor, worker_id: str):
    """Process job with concurrency limit."""
    async with job_semaphore:
        await process_full_blog(job, executor, worker_id)
```

---

## 4. External Dependency Circuit Breakers

### File: src/monitoring/circuit_breaker.py (ENHANCED)

```python
"""Circuit breakers for external dependencies."""

import asyncio
import time
from typing import Any, Callable
from enum import Enum

from src.config.logging_config import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ExternalCircuitBreaker:
    """
    Production-grade circuit breaker for external APIs.
    
    Features:
    - Rolling window failure detection
    - Configurable thresholds
    - Half-open recovery
    - Hard timeout enforcement
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        call_timeout: int = 30,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.call_timeout = call_timeout
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker and timeout."""
        
        # Check if open
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("circuit_half_open", name=self.name)
            else:
                logger.warning("circuit_open_reject", name=self.name)
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")
        
        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.call_timeout,
            )
            self._on_success()
            return result
            
        except asyncio.TimeoutError:
            self._on_failure()
            raise TimeoutError(f"{self.name} call timed out after {self.call_timeout}s")
            
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        self.success_count += 1
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info("circuit_closed", name=self.name)
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "circuit_opened",
                name=self.name,
                failures=self.failure_count,
            )


class CircuitOpenError(Exception):
    pass


# Production circuit breakers
gemini_circuit_breaker = ExternalCircuitBreaker(
    name="gemini",
    failure_threshold=5,
    recovery_timeout=30,
    call_timeout=60,  # LLM calls can be slow
)

tavily_circuit_breaker = ExternalCircuitBreaker(
    name="tavily",
    failure_threshold=3,
    recovery_timeout=30,
    call_timeout=15,  # Research should be fast
)

db_circuit_breaker = ExternalCircuitBreaker(
    name="database",
    failure_threshold=10,
    recovery_timeout=10,
    call_timeout=5,  # DB should be fast
)
```

---

## 5. PostgreSQL Fast-Fail Configuration

### File: src/config/database_config.py (UPDATES)

```python
class DatabaseSettings(BaseSettings):
    # Connection pool limits
    database_pool_size: int = 10
    database_max_overflow: int = 5
    
    # Timeouts for fast-fail
    database_connect_timeout: int = 5  # Connection acquire timeout
    database_command_timeout: int = 10  # Query timeout
    
    # Pool behavior
    database_pool_recycle: int = 3600  # Recycle connections after 1 hour
    database_pool_pre_ping: bool = True  # Verify connections before use
```

### File: src/models/repository.py (UPDATES)

```python
def get_engine():
    """Get database engine with fast-fail settings."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            db_settings.database_url,
            
            # Pool limits
            pool_size=db_settings.database_pool_size,
            max_overflow=db_settings.database_max_overflow,
            
            # Fast-fail settings
            pool_pre_ping=True,
            pool_recycle=3600,
            
            # Connection timeout
            connect_args={
                "timeout": db_settings.database_connect_timeout,
                "command_timeout": db_settings.database_command_timeout,
            },
            
            echo=False,
        )
    return _engine
```

---

## 6. API Route Updates with Backpressure

### File: src/api/routes/blog.py (UPDATES)

```python
from src.core.backpressure import (
    api_concurrency_limiter,
    ConcurrencyLimitExceeded,
)
from src.core.task_queue import QueueFullError


@router.post("/blog/generate", status_code=202)
async def generate_blog(request: BlogGenerationRequest, ...):
    """Generate blog with full backpressure protection."""
    
    try:
        # 1. Concurrency limit check
        async with api_concurrency_limiter:
            
            # 2. Rate limit check (existing)
            allowed, msg = await rate_limit_guard.check_all_limits(...)
            if not allowed:
                raise HTTPException(429, msg)
            
            # 3. Input validation (existing)
            valid, msg = input_guard.validate_input(...)
            if not valid:
                raise HTTPException(400, msg)
            
            # 4. DB write (fast-fail via pool timeout)
            blog = await db_repository.create_blog(...)
            
            # 5. Enqueue (with depth check)
            task_id = await enqueue_blog_generation(...)
            
            return BlogGenerationResponse(...)
    
    except ConcurrencyLimitExceeded:
        raise HTTPException(
            status_code=503,
            detail="Service overloaded. Retry after 5 seconds.",
            headers={"Retry-After": "5"},
        )
    
    except QueueFullError:
        raise HTTPException(
            status_code=503,
            detail="Queue at capacity. Retry after 10 seconds.",
            headers={"Retry-After": "10"},
        )
```

---

## 7. End-to-End Load Shedding Behavior

| Scenario | Control Point | Behavior |
|----------|---------------|----------|
| **Gemini outage** | Worker circuit breaker | Opens after 5 failures, jobs fail fast, requeue with backoff |
| **Tavily outage** | Worker circuit breaker | Opens after 3 failures, research stage fails, uses fallback |
| **Traffic spike** | Queue depth (1000) | Returns 503 when full, clients retry |
| **API overload** | Concurrency semaphore (100) | Returns 503 after 5s wait, no thread exhaustion |
| **DB slowdown** | Pool timeout (5s) | Requests fail fast, no connection wait |
| **Worker overload** | Job semaphore (3) | Queue absorbs load, workers pace themselves |

---

## 8. Configuration Summary

| Control Point | Setting | Value | Location |
|---------------|---------|-------|----------|
| API concurrency | MAX_CONCURRENT | 100 | `backpressure.py` |
| Queue depth | MAX_QUEUE_DEPTH | 1000 | `task_queue.py` |
| Worker jobs | MAX_CONCURRENT_JOBS | 3 | `blog_worker.py` |
| Gemini timeout | call_timeout | 60s | `circuit_breaker.py` |
| Gemini breaker | failure_threshold | 5 | `circuit_breaker.py` |
| Tavily timeout | call_timeout | 15s | `circuit_breaker.py` |
| Tavily breaker | failure_threshold | 3 | `circuit_breaker.py` |
| DB pool | pool_size | 10 | `database_config.py` |
| DB connect timeout | connect_timeout | 5s | `database_config.py` |
| DB query timeout | command_timeout | 10s | `database_config.py` |
| Redis connect | socket_timeout | 5s | `session_store.py` |

---

## 9. File-by-File Implementation Map

| File | Action | Changes |
|------|--------|---------|
| `src/core/backpressure.py` | **NEW** | ConcurrencyLimiter, CircuitBreaker, QueueFullError |
| `src/core/task_queue.py` | **UPDATE** | Add MAX_QUEUE_DEPTH check in enqueue() |
| `src/api/routes/blog.py` | **UPDATE** | Wrap with api_concurrency_limiter |
| `src/api/middleware.py` | **UPDATE** | Already has ConcurrencyLimitMiddleware |
| `src/workers/blog_worker.py` | **UPDATE** | Add job_semaphore for MAX_CONCURRENT_JOBS |
| `src/monitoring/circuit_breaker.py` | **UPDATE** | Add timeout, enhance recovery |
| `src/agents/pipeline.py` | **VERIFY** | Already uses circuit breakers |
| `src/config/database_config.py` | **UPDATE** | Add timeout settings |
| `src/models/repository.py` | **UPDATE** | Configure pool with timeouts |
| `src/core/session_store.py` | **UPDATE** | Add socket timeouts |

---

*This implementation provides defense-in-depth backpressure at every service boundary.*
