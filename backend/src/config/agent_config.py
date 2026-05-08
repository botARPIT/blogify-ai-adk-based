"""Model configurations for ADK agents."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""

    name: str
    temperature: float = 0.7
    max_output_tokens: Optional[int] = None
    retry_attempts: int = 3


INTENT_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

OUTLINE_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

RESEARCH_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

WRITER_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=16384,
    retry_attempts=3,
)

EDITOR_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

CHATBOT_MODEL = ModelConfig(
    name="gemini-2.0-flash",
    temperature=0.7,
    max_output_tokens=4096,
    retry_attempts=3,
)


def _get_default_retry_config() -> None:
    """Get default retry configuration."""
    return None


def create_retry_config(attempts: int = 3) -> None:
    """Create retry configuration with specified attempts."""
    return None