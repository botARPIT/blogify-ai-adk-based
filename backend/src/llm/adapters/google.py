"""Google Gemini adapter.

Translates a :class:`~src.llm.config.ModelConfig` onto ADK's native ``Gemini``
model. No routing syntax, no name mangling — ``config.name`` is already a real
Gemini model id.

Generation parameters
---------------------
In ADK 2.x, ``Gemini`` accepts only connection-level fields (``model``,
``base_url``, ``retry_options``, ...). ``temperature`` and ``max_output_tokens``
are **not** model constructor fields; they are per-request and reach the API via
``LlmAgent.generate_content_config``. Passing them to ``Gemini(...)`` is silently
dropped by pydantic, which would make a stage's configured sampling appear to be
applied when it was not. This adapter therefore forwards only what ``Gemini``
actually honours.
"""

from __future__ import annotations

from google.adk.models.google_llm import Gemini
from google.genai import types

from src.llm.config import ModelConfig

RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]


def build_gemini_retry_options(config: ModelConfig) -> types.HttpRetryOptions:
    """Map ``retry_attempts`` onto Gemini's HTTP retry policy."""
    return types.HttpRetryOptions(
        attempts=config.retry_attempts,
        exp_base=2,
        initial_delay=2,
        http_status_codes=list(RETRYABLE_STATUS_CODES),
    )


def create_google_model(config: ModelConfig) -> Gemini:
    """Build a ``Gemini`` model for ``config``."""
    return Gemini(
        model=config.name,
        retry_options=build_gemini_retry_options(config),
    )
