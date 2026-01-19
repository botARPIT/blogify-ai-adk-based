"""Agent configuration for models, retries, and parameters."""

from dataclasses import dataclass
from typing import Final
from google.genai import types


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
) -> types.HttpRetryOptions:
    """Create retry configuration with exponential backoff and jitter."""
    return types.HttpRetryOptions(
        attempts=attempts,
        exp_base=multiplier,
        initial_delay=initial_delay,
        http_status_codes=[429, 500, 502, 503, 504],
    )


# Default retry configuration
DEFAULT_RETRY_CONFIG: Final[types.HttpRetryOptions] = create_retry_config()
