"""Agent configuration for models, retries, and parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from google.genai import types as genai_types


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a specific model."""

    name: str
    temperature: float
    max_output_tokens: int
    retry_attempts: int = 3


# Model configurations
INTENT_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash-lite", temperature=0.3, max_output_tokens=500, retry_attempts=3
)

OUTLINE_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash-lite", temperature=0.3, max_output_tokens=2000, retry_attempts=3
)

RESEARCH_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash-lite", temperature=0.1, max_output_tokens=300, retry_attempts=3
)

WRITER_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash", temperature=0.7, max_output_tokens=3000, retry_attempts=3
)

EDITOR_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash-lite", temperature=0.2, max_output_tokens=2000, retry_attempts=3
)

CHATBOT_MODEL: Final[ModelConfig] = ModelConfig(
    name="gemini-2.5-flash", temperature=0.8, max_output_tokens=1000, retry_attempts=2
)


def create_retry_config(
    attempts: int = 3,
    initial_delay: int = 2,
    max_delay: int = 30,
    multiplier: float = 2.0,
) -> Any:
    """Create retry configuration with exponential backoff and jitter.

    Lazily imports google.genai so this module remains importable
    without the ADK/GenAI SDK installed (e.g. during unit tests).
    """
    from google.genai import types  # lazy import — only when actually called

    return types.HttpRetryOptions(
        attempts=attempts,
        exp_base=multiplier,
        initial_delay=initial_delay,
        http_status_codes=[429, 500, 502, 503, 504],
    )


# Lazy default: evaluates only when first accessed by agent construction code.
def _get_default_retry_config() -> Any:
    """Return a default retry config instance (lazy)."""
    return create_retry_config()


# Kept as a named sentinel so existing code that references DEFAULT_RETRY_CONFIG
# can call _get_default_retry_config() instead.  Will be cleaned up in Phase 2.
DEFAULT_RETRY_CONFIG: Final = None  # type: ignore[assignment]  # placeholder — use _get_default_retry_config()
