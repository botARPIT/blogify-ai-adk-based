"""Model factory.

The factory is the single decision point for *how* a configured model becomes a
live ADK model object:

    ModelConfig
        |
        v
      factory
        |-- GOOGLE --> Google adapter  --> Gemini
        `-- OLLAMA --> LiteLLM adapter --> OpenAI-compatible endpoint

Agents call :func:`create_model` and nothing else. They must never construct
``Gemini``, ``LiteLlm`` or a provider client directly.
"""

from typing import Any

from src.llm.adapters.google import create_google_model
from src.llm.adapters.litellm import create_litellm_model
from src.llm.config import LLMProvider, ModelConfig


def create_model(config: ModelConfig) -> Any:
    """Build the ADK model object for ``config``."""
    if config.provider is LLMProvider.GOOGLE:
        return create_google_model(config)

    if config.provider is LLMProvider.OLLAMA:
        return create_litellm_model(config)

    raise ValueError(f"Unsupported LLM provider: {config.provider}")
