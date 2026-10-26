"""Provider-agnostic LLM configuration.

``LLMProvider`` answers *who* serves the model. ``LLMTransport`` answers *how*
the request is spoken. LiteLLM is intentionally **not** a provider: it is a
client library, and it appears only inside
:mod:`src.llm.adapters.litellm`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LLMProvider(StrEnum):
    """An upstream that serves models. Application-level concern."""

    GOOGLE = "google"
    OLLAMA = "ollama"


class LLMTransport(StrEnum):
    """The wire protocol spoken to a provider. Connection-level concern."""

    GOOGLE_NATIVE = "google_native"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA_NATIVE = "ollama_native"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    provider: LLMProvider
    transport: LLMTransport
    name: str

    api_base: str | None = None
    api_key: str | None = None

    temperature: float = 0.7
    max_output_tokens: int | None = None
    retry_attempts: int = 3

    request_params: dict[str, Any] = field(default_factory=dict)
