"""Model configurations for ADK agents."""

import asyncio
from dataclasses import dataclass

from google.genai import types


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""

    name: str
    temperature: float = 0.7
    max_output_tokens: int | None = None
    retry_attempts: int = 3


INTENT_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

OUTLINE_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

RESEARCH_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

WRITER_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=16384,
    retry_attempts=3,
)

EDITOR_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=8192,
    retry_attempts=3,
)

CHATBOT_MODEL = ModelConfig(
    name="gemini-2.5-flash",
    temperature=0.7,
    max_output_tokens=4096,
    retry_attempts=3,
)


def _get_default_retry_config() -> types.HttpRetryOptions:
    """Get default retry configuration."""
    return types.HttpRetryOptions(
        attempts=7,
        initial_delay=8,
        exp_base=2,
        jitter=1.0,
        http_status_codes=[429, 500, 502, 503],
    )


def create_retry_config(attempts: int = 7) -> types.HttpRetryOptions:
    """Create retry configuration with specified attempts."""
    return types.HttpRetryOptions(
        attempts=attempts,
        initial_delay=8,
        exp_base=2,
        jitter=1.0,
        http_status_codes=[429, 500, 502, 503],
    )


async def agent_delay() -> None:
    """Artificial delay after each agent run."""
    await asyncio.sleep(2)
