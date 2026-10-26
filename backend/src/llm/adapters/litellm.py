"""LiteLLM adapter — the translation boundary.

This module is the *only* place in the application allowed to know about
LiteLLM's provider/model syntax. Application configuration
(:mod:`src.llm.model_configs`) carries provider-native names such as
``gemma4:31b``; LiteLLM addresses the very same model as ``openai/gemma4:31b``.
That prefix is a routing detail of the client library and must never leak into
application configuration.

The adapter owns:

* LiteLLM provider/model syntax
* LiteLLM retry parameter mapping
* ``max_output_tokens`` -> LiteLLM token parameter mapping
* request parameter merging

It deliberately owns **no** model-specific behaviour. Anything that would
require a branch such as ``if config.name == "gpt-oss"`` belongs in
:mod:`src.llm.model_configs` as model-specific ``request_params``, because it
describes the model, not the transport.
"""

from __future__ import annotations

from typing import Any

from google.adk.models.lite_llm import LiteLlm

from src.llm.config import LLMTransport, ModelConfig

#: LiteLLM provider prefix used for OpenAI-compatible endpoints. Ollama Cloud
#: and self-hosted Ollama both speak the OpenAI chat-completions dialect.
OPENAI_COMPATIBLE_PREFIX = "openai/"


def to_litellm_model_name(config: ModelConfig) -> str:
    """Map an application model name onto LiteLLM's ``provider/name`` syntax.

    A name that already carries an explicit ``provider/`` prefix is left alone
    so that a caller can still address a non-OpenAI-compatible upstream. An
    unprefixed name is assumed OpenAI-compatible, which is the only dialect
    LiteLLM is wired for here.
    """
    if "/" in config.name:
        return config.name
    return f"{OPENAI_COMPATIBLE_PREFIX}{config.name}"


def build_litellm_kwargs(config: ModelConfig) -> dict[str, Any]:
    """Translate ``config`` into ``LiteLlm`` keyword arguments."""
    if config.transport is not LLMTransport.OPENAI_COMPATIBLE:
        raise ValueError(
            f"Unsupported LiteLLM transport: {config.transport}. "
            f"The LiteLLM adapter only speaks {LLMTransport.OPENAI_COMPATIBLE}; "
            "the Ollama native dialect (/api/generate) is intentionally not "
            "routed through LiteLLM because it is not OpenAI-compatible."
        )

    # Required. Without an explicit base URL LiteLLM falls back to guessing the
    # upstream from the model name, which is how a cloud Ollama deployment ends
    # up being called on its native /api/generate path instead of /v1.
    if not config.api_base:
        raise ValueError(
            "ModelConfig.api_base is required for OPENAI_COMPATIBLE transport; "
            "refusing to let LiteLLM infer the endpoint."
        )

    kwargs: dict[str, Any] = {
        "model": to_litellm_model_name(config),
        "api_base": config.api_base,
        "api_key": config.api_key,
        "temperature": config.temperature,
        "num_retries": config.retry_attempts,
    }

    if config.max_output_tokens is not None:
        kwargs["max_completion_tokens"] = config.max_output_tokens

    kwargs.update(config.request_params)

    return kwargs


def create_litellm_model(config: ModelConfig) -> LiteLlm:
    """Build a ``LiteLlm`` model for ``config``."""
    return LiteLlm(**build_litellm_kwargs(config))
