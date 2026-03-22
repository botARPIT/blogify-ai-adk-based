"""Circuit breaker for API resilience."""

import time
from enum import Enum
from typing import Callable, TypeVar

from src.config import settings
from src.config.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """Circuit breaker pattern for API calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_timeout: int | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self.recovery_timeout = recovery_timeout or settings.circuit_breaker_recovery_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None

    def _should_attempt_reset(self) -> bool:
        """Check if circuit should attempt reset to HALF_OPEN."""
        if self.state != CircuitState.OPEN:
            return False

        if self.last_failure_time is None:
            return False

        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    async def call(self, func: Callable[[], T]) -> T:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
        
        Returns:
            Function result
        
        Raises:
            RuntimeError: If circuit is open
        """
        # Check if should attempt reset
        if self._should_attempt_reset():
            logger.info("circuit_breaker_half_open", name=self.name)
            self.state = CircuitState.HALF_OPEN

        # Reject if circuit is open
        if self.state == CircuitState.OPEN:
            logger.error("circuit_breaker_open", name=self.name)
            raise RuntimeError(f"Circuit breaker '{self.name}' is OPEN")

        try:
            # Execute function
            result = await func()

            # Success - reset if in HALF_OPEN
            if self.state == CircuitState.HALF_OPEN:
                logger.info("circuit_breaker_closed", name=self.name)
                self.state = CircuitState.CLOSED
                self.failure_count = 0

            return result

        except Exception as e:
            # Record failure
            self.failure_count += 1
            self.last_failure_time = time.time()

            logger.warning(
                "circuit_breaker_failure",
                name=self.name,
                failures=self.failure_count,
                threshold=self.failure_threshold,
                error=str(e),
            )

            # Open circuit if threshold reached
            if self.failure_count >= self.failure_threshold:
                logger.error("circuit_breaker_opened", name=self.name)
                self.state = CircuitState.OPEN

            raise


# Global circuit breakers
gemini_circuit_breaker = CircuitBreaker(name="gemini_api")
tavily_circuit_breaker = CircuitBreaker(name="tavily_api")
