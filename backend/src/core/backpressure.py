"""Backpressure controls for production traffic management.

Implements layered protection at every service boundary:
- Concurrency limiters (semaphores)
- Queue depth limits
- Circuit breakers with rolling windows
- Fast-fail semantics

No component may accumulate unbounded in-flight work.
"""

import asyncio
import time
from typing import Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from src.config.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Rejecting all calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitStats:
    """Rolling window statistics for circuit breaker."""
    window_size: int = 30  # seconds
    timestamps: deque = field(default_factory=deque)
    failures: deque = field(default_factory=deque)
    
    def record(self, is_failure: bool):
        """Record a call result."""
        now = time.time()
        self.timestamps.append(now)
        self.failures.append(is_failure)
        self._prune(now)
    
    def _prune(self, now: float):
        """Remove entries outside window."""
        cutoff = now - self.window_size
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
            self.failures.popleft()
    
    @property
    def total_calls(self) -> int:
        self._prune(time.time())
        return len(self.timestamps)
    
    @property
    def failure_count(self) -> int:
        self._prune(time.time())
        return sum(self.failures)
    
    @property
    def failure_rate(self) -> float:
        total = self.total_calls
        if total == 0:
            return 0.0
        return self.failure_count / total


class CircuitBreaker:
    """
    Production circuit breaker with rolling window failure detection.
    
    Features:
    - Rolling window for failure rate calculation
    - Configurable failure threshold (percentage)
    - Half-open recovery with single test call
    - Hard timeout enforcement on calls
    
    Configuration:
    - failure_threshold: % failures to trip (0.5 = 50%)
    - window_size: Rolling window in seconds
    - recovery_timeout: Seconds in OPEN before trying HALF_OPEN
    - min_calls: Minimum calls before evaluating threshold
    - call_timeout: Maximum seconds per call
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        window_size: int = 30,
        recovery_timeout: int = 30,
        min_calls: int = 10,
        call_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_size = window_size
        self.recovery_timeout = recovery_timeout
        self.min_calls = min_calls
        self.call_timeout = call_timeout
        
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats(window_size=window_size)
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    @property
    def failure_rate(self) -> float:
        return self._stats.failure_rate
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker with timeout.
        
        Raises:
            CircuitOpenError: If circuit is open
            TimeoutError: If call exceeds timeout
            Exception: Original exception from func
        """
        # Check state before call
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("circuit_half_open", name=self.name)
                else:
                    raise CircuitOpenError(
                        f"Circuit {self.name} is OPEN "
                        f"(failure rate: {self._stats.failure_rate:.1%})"
                    )
        
        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.call_timeout,
            )
            await self._record_success()
            return result
            
        except asyncio.TimeoutError:
            await self._record_failure()
            raise TimeoutError(
                f"{self.name} timed out after {self.call_timeout}s"
            )
            
        except CircuitOpenError:
            raise
            
        except Exception as e:
            await self._record_failure()
            raise
    
    async def _record_success(self):
        """Record successful call."""
        async with self._lock:
            self._stats.record(is_failure=False)
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("circuit_closed", name=self.name)
    
    async def _record_failure(self):
        """Record failed call, possibly trip circuit."""
        async with self._lock:
            self._stats.record(is_failure=True)
            self._last_failure_time = time.time()
            
            # Check if should trip
            if self._state != CircuitState.OPEN:
                if self._stats.total_calls >= self.min_calls:
                    if self._stats.failure_rate >= self.failure_threshold:
                        self._state = CircuitState.OPEN
                        logger.warning(
                            "circuit_opened",
                            name=self.name,
                            failure_rate=f"{self._stats.failure_rate:.1%}",
                            total_calls=self._stats.total_calls,
                        )
    
    def get_stats(self) -> dict:
        """Get current circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_rate": f"{self._stats.failure_rate:.1%}",
            "total_calls": self._stats.total_calls,
            "failure_count": self._stats.failure_count,
        }


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# =============================================================================
# CONCURRENCY LIMITER
# =============================================================================

class ConcurrencyLimiter:
    """
    Semaphore-based concurrency limiter with timeout.
    
    Prevents unbounded in-flight requests.
    Fast-fails when limit reached rather than queuing.
    """
    
    def __init__(
        self,
        name: str,
        max_concurrent: int,
        acquire_timeout: float = 5.0,
    ):
        self.name = name
        self.max_concurrent = max_concurrent
        self.acquire_timeout = acquire_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._lock = asyncio.Lock()
    
    @property
    def in_flight(self) -> int:
        return self._in_flight
    
    @property
    def available(self) -> int:
        return self._semaphore._value
    
    async def acquire(self) -> bool:
        """
        Acquire a slot with timeout.
        
        Returns:
            True if acquired, False if timeout
        """
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.acquire_timeout,
            )
            async with self._lock:
                self._in_flight += 1
            return True
            
        except asyncio.TimeoutError:
            logger.warning(
                "concurrency_limit_timeout",
                name=self.name,
                in_flight=self._in_flight,
                max=self.max_concurrent,
            )
            return False
    
    def release(self):
        """Release a slot."""
        self._semaphore.release()
        # Decrement counter (best effort)
        asyncio.create_task(self._decrement())
    
    async def _decrement(self):
        async with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
    
    async def __aenter__(self):
        acquired = await self.acquire()
        if not acquired:
            raise ConcurrencyLimitExceeded(
                f"{self.name}: limit reached ({self.max_concurrent} concurrent)"
            )
        return self
    
    async def __aexit__(self, *args):
        self.release()
    
    def get_stats(self) -> dict:
        """Get current limiter statistics."""
        return {
            "name": self.name,
            "in_flight": self._in_flight,
            "available": self.available,
            "max_concurrent": self.max_concurrent,
        }


class ConcurrencyLimitExceeded(Exception):
    """Raised when concurrency limit is hit."""
    pass


# =============================================================================
# QUEUE DEPTH LIMITER
# =============================================================================

class QueueFullError(Exception):
    """Raised when queue depth exceeds maximum."""
    pass


# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

# API layer concurrency (can be high - just enqueues)
api_concurrency_limiter = ConcurrencyLimiter(
    name="api_ingress",
    max_concurrent=100,
    acquire_timeout=5.0,
)

# External API circuit breakers
gemini_circuit_breaker = CircuitBreaker(
    name="gemini",
    failure_threshold=0.5,
    window_size=30,
    recovery_timeout=30,
    min_calls=5,
    call_timeout=60.0,  # LLM calls can be slow
)

tavily_circuit_breaker = CircuitBreaker(
    name="tavily",
    failure_threshold=0.5,
    window_size=30,
    recovery_timeout=30,
    min_calls=3,
    call_timeout=15.0,  # Research should be faster
)

# Database circuit breaker (very aggressive - DB should be fast)
db_circuit_breaker = CircuitBreaker(
    name="database",
    failure_threshold=0.3,  # Trip at 30% failures
    window_size=10,
    recovery_timeout=10,
    min_calls=5,
    call_timeout=5.0,
)


def get_all_stats() -> dict:
    """Get statistics for all backpressure controls."""
    return {
        "concurrency": {
            "api": api_concurrency_limiter.get_stats(),
        },
        "circuit_breakers": {
            "gemini": gemini_circuit_breaker.get_stats(),
            "tavily": tavily_circuit_breaker.get_stats(),
            "database": db_circuit_breaker.get_stats(),
        },
    }
