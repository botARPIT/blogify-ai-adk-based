"""Agent runtime configuration.

Model identity lives in :mod:`src.llm.model_configs` and model construction in
:mod:`src.llm.factory`. This module keeps only runtime knobs that are not model
selection.
"""

import asyncio

from google.genai import types


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
