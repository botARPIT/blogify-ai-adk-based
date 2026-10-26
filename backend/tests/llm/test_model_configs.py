"""Application model configuration contract.

The names written here must be the provider's own names. LiteLLM routing syntax
in application configuration is a defect, not a style preference.
"""

from __future__ import annotations

import re
from dataclasses import fields

import pytest

from src.llm.config import LLMProvider, LLMTransport, ModelConfig
from src.llm.model_configs import (
    CHATBOT_MODEL,
    EDITOR_MODEL,
    GEMINI_25_FLASH,
    GEMMA_31B,
    GPT_OSS_120B,
    INTENT_MODEL,
    KNOWN_MODELS,
    OUTLINE_MODEL,
    OUTLINE_REVIEW_MODEL,
    RESEARCH_MODEL,
    WRITER_MODEL,
)

#: A LiteLLM-style routing prefix appearing in an application model name.
ROUTING_PREFIX = re.compile(r"^(openai|ollama|gemini|vertex_ai|anthropic|groq)/")


class TestCatalog:
    def test_gemma_31b_identity(self):
        assert GEMMA_31B.provider is LLMProvider.OLLAMA
        assert GEMMA_31B.transport is LLMTransport.OPENAI_COMPATIBLE
        assert GEMMA_31B.name == "gemma4:31b"
        assert GEMMA_31B.api_base == "https://ollama.com/v1"

    def test_gpt_oss_120b_identity(self):
        assert GPT_OSS_120B.provider is LLMProvider.OLLAMA
        assert GPT_OSS_120B.transport is LLMTransport.OPENAI_COMPATIBLE
        assert GPT_OSS_120B.name == "gpt-oss:120b"
        assert GPT_OSS_120B.api_base == "https://ollama.com/v1"

    def test_gemini_identity(self):
        assert GEMINI_25_FLASH.provider is LLMProvider.GOOGLE
        assert GEMINI_25_FLASH.transport is LLMTransport.GOOGLE_NATIVE
        assert GEMINI_25_FLASH.name == "gemini-2.5-flash"

    def test_gpt_oss_declares_its_own_reasoning_flag(self):
        assert GPT_OSS_120B.request_params == {"extra_body": {"include_reasoning": False}}

    def test_reasoning_flag_is_not_inherited_by_other_models(self):
        """Model-specific options must not leak onto unrelated models."""
        assert "extra_body" not in GEMMA_31B.request_params
        assert "extra_body" not in GEMINI_25_FLASH.request_params

    @pytest.mark.parametrize("config", KNOWN_MODELS, ids=lambda c: c.name)
    def test_no_provider_routing_prefix_in_application_config(self, config):
        assert ROUTING_PREFIX.match(config.name) is None

    @pytest.mark.parametrize("config", KNOWN_MODELS, ids=lambda c: c.name)
    def test_openai_prefix_absent_from_every_config_field(self, config):
        for field in fields(config):
            value = getattr(config, field.name)
            if isinstance(value, str):
                assert not value.startswith("openai/"), field.name
            elif isinstance(value, dict):
                for key in value:
                    assert not str(key).startswith("openai/"), field.name


class TestStageConfiguration:
    @pytest.mark.parametrize(
        "config",
        [
            INTENT_MODEL,
            OUTLINE_MODEL,
            RESEARCH_MODEL,
            WRITER_MODEL,
            EDITOR_MODEL,
            CHATBOT_MODEL,
            OUTLINE_REVIEW_MODEL,
        ],
        ids=lambda c: f"stage-{c.max_output_tokens}",
    )
    def test_stage_models_are_well_formed(self, config):
        assert isinstance(config, ModelConfig)
        assert config.name.strip()
        assert config.provider in tuple(LLMProvider)
        assert config.transport in tuple(LLMTransport)

    def test_outline_review_reuses_outline_model(self):
        assert OUTLINE_REVIEW_MODEL == OUTLINE_MODEL

    def test_stage_temperatures_are_distinct_decisions(self):
        assert RESEARCH_MODEL.temperature < OUTLINE_MODEL.temperature
        assert WRITER_MODEL.temperature > EDITOR_MODEL.temperature


class TestProviderEnum:
    def test_litellm_is_not_an_application_provider(self):
        assert not hasattr(LLMProvider, "LITELLM")
        assert [p.value for p in LLMProvider] == ["google", "ollama"]

    def test_transport_enum_separates_dialect_from_vendor(self):
        assert [t.value for t in LLMTransport] == [
            "google_native",
            "openai_compatible",
            "ollama_native",
        ]


class TestGoogleRouting:
    def test_google_provider_yields_google_native_stage_configs(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "google")
        monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
        import importlib

        from src.llm import model_configs

        reloaded = importlib.reload(model_configs)
        try:
            assert reloaded.OUTLINE_MODEL.provider is LLMProvider.GOOGLE
            assert reloaded.OUTLINE_MODEL.transport is LLMTransport.GOOGLE_NATIVE
        finally:
            monkeypatch.delenv("LLM_PROVIDER", raising=False)
            monkeypatch.delenv("LLM_MODEL", raising=False)
            importlib.reload(model_configs)

    def test_unknown_provider_is_rejected_with_valid_options(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "litellm")
        import importlib

        from src.llm import model_configs

        try:
            with pytest.raises(ValueError, match="Expected one of"):
                importlib.reload(model_configs)
        finally:
            monkeypatch.delenv("LLM_PROVIDER", raising=False)
            importlib.reload(model_configs)
