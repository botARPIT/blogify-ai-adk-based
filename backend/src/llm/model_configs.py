"""Application model configuration.

This module answers *which model each stage uses*. It carries **provider-native**
model identity: the name written here is the real upstream name, exactly as the
provider itself knows it. LiteLLM routing syntax such as ``openai/`` is a client
library detail and belongs only in :mod:`src.llm.adapters.litellm`.

Model-specific options stay model-specific. For example GPT-OSS suppresses its
reasoning trace through a vendor-specific ``extra_body`` flag; that flag is a
property of *GPT-OSS*, not of every model served by Ollama, so it is declared
next to GPT-OSS and nowhere else.
"""

from __future__ import annotations

import os
from dataclasses import replace

from src.llm.config import (
    LLMProvider,
    LLMTransport,
    ModelConfig,
)

DEFAULT_OLLAMA_BASE_URL = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL = "gemma4:31b"
DEFAULT_GOOGLE_MODEL = "gemini-2.5-flash"


def _llm_provider() -> LLMProvider:
    raw = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not raw:
        return LLMProvider.OLLAMA
    try:
        return LLMProvider(raw)
    except ValueError as exc:
        valid = ", ".join(provider.value for provider in LLMProvider)
        raise ValueError(f"Unsupported LLM_PROVIDER={raw!r}. Expected one of: {valid}.") from exc


# ---------------------------------------------------------------------------
# Model catalog
#
# Names below are provider-native. Do not prefix them with a LiteLLM provider.
# ---------------------------------------------------------------------------

GEMMA_31B = ModelConfig(
    provider=LLMProvider.OLLAMA,
    transport=LLMTransport.OPENAI_COMPATIBLE,
    name="gemma4:31b",
    api_base=DEFAULT_OLLAMA_BASE_URL,
    api_key=os.getenv("LLM_API_KEY"),
)

GPT_OSS_120B = ModelConfig(
    provider=LLMProvider.OLLAMA,
    transport=LLMTransport.OPENAI_COMPATIBLE,
    name="gpt-oss:120b",
    api_base=DEFAULT_OLLAMA_BASE_URL,
    api_key=os.getenv("LLM_API_KEY"),
    # Model-specific: GPT-OSS otherwise emits a reasoning trace the editor
    # would treat as review commentary. Not an Ollama-wide setting.
    request_params={"extra_body": {"include_reasoning": False}},
)

GEMINI_25_FLASH = ModelConfig(
    provider=LLMProvider.GOOGLE,
    transport=LLMTransport.GOOGLE_NATIVE,
    name="gemini-2.5-flash",
    api_key=os.getenv("GOOGLE_API_KEY"),
)

#: Every model identity the application is allowed to select by name.
KNOWN_MODELS = (GEMMA_31B, GPT_OSS_120B, GEMINI_25_FLASH)


# ---------------------------------------------------------------------------
# Base config
# ---------------------------------------------------------------------------


def _base_config() -> ModelConfig:
    provider = _llm_provider()
    if provider is LLMProvider.GOOGLE:
        return replace(
            GEMINI_25_FLASH,
            name=os.getenv("LLM_MODEL", DEFAULT_GOOGLE_MODEL),
        )

    # Pick the catalog entry whose model-specific parameters match the model
    # actually being used, then let LLM_MODEL override only the name.
    template = GPT_OSS_120B if _configured_model_is_gpt_oss() else GEMMA_31B
    return replace(
        template,
        name=os.getenv("LLM_MODEL", template.name),
        api_base=os.getenv("LLM_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        api_key=os.getenv("LLM_API_KEY"),
    )


def _configured_model_is_gpt_oss() -> bool:
    configured = os.getenv("LLM_MODEL")
    if configured is None:
        return False
    return configured.split("/", 1)[-1].startswith("gpt-oss")


# ---------------------------------------------------------------------------
# Stage configuration
#
# Model choice is a configuration decision, never an agent implementation detail.
# ---------------------------------------------------------------------------

_BASE = _base_config()

INTENT_MODEL = replace(
    _BASE,
    temperature=0.3,
    max_output_tokens=500,
    retry_attempts=3,
)

OUTLINE_MODEL = replace(
    _BASE,
    temperature=0.3,
    max_output_tokens=2000,
    retry_attempts=3,
)

RESEARCH_MODEL = replace(
    _BASE,
    temperature=0.1,
    max_output_tokens=300,
    retry_attempts=3,
)

WRITER_MODEL = replace(
    _BASE,
    temperature=0.7,
    max_output_tokens=3000,
    retry_attempts=3,
)

EDITOR_MODEL = replace(
    _BASE,
    temperature=0.2,
    max_output_tokens=2000,
    retry_attempts=3,
)

CHATBOT_MODEL = replace(
    _BASE,
    temperature=0.8,
    max_output_tokens=1000,
    retry_attempts=2,
)

OUTLINE_REVIEW_MODEL = OUTLINE_MODEL
