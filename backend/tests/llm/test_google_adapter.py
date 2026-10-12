"""Google adapter and factory routing."""

from __future__ import annotations

import pytest
from google.adk.models.google_llm import Gemini

from src.llm.adapters.google import create_google_model
from src.llm.config import LLMProvider, LLMTransport, ModelConfig
from src.llm.factory import create_model


def _google_config(**overrides) -> ModelConfig:
    base = {
        "provider": LLMProvider.GOOGLE,
        "transport": LLMTransport.GOOGLE_NATIVE,
        "name": "gemini-2.5-flash",
        "api_key": "test-key",
        "temperature": 0.7,
        "max_output_tokens": 1000,
        "retry_attempts": 3,
    }
    base.update(overrides)
    return ModelConfig(**base)


class TestGoogleAdapter:
    def test_builds_a_gemini_model_with_native_name(self):
        model = create_google_model(_google_config())
        assert isinstance(model, Gemini)
        assert model.model == "gemini-2.5-flash"

    def test_retry_attempts_reach_http_retry_options(self):
        model = create_google_model(_google_config(retry_attempts=5))
        assert model.retry_options is not None
        assert model.retry_options.attempts == 5

    def test_retryable_status_codes_include_gateway_errors(self):
        model = create_google_model(_google_config())
        assert model.retry_options is not None
        assert 429 in model.retry_options.http_status_codes
        assert 503 in model.retry_options.http_status_codes

    def test_adapter_does_not_pass_fields_gemini_would_drop(self):
        """ADK 2.x `Gemini` ignores unknown kwargs, silently.

        Passing temperature/max_output_tokens there would look configured while
        never reaching the API, so the adapter must not send them.
        """
        import inspect

        from src.llm.adapters import google

        source = inspect.getsource(google.create_google_model)
        assert "temperature=" not in source
        assert "max_output_tokens=" not in source

        model = create_google_model(_google_config(temperature=0.25, max_output_tokens=512))
        assert "temperature" not in type(model).model_fields
        assert "max_output_tokens" not in type(model).model_fields


class TestFactoryRouting:
    def test_google_provider_routes_to_gemini(self):
        assert isinstance(create_model(_google_config()), Gemini)

    def test_ollama_provider_routes_to_litellm(self):
        config = ModelConfig(
            provider=LLMProvider.OLLAMA,
            transport=LLMTransport.OPENAI_COMPATIBLE,
            name="gemma4:31b",
            api_base="https://ollama.com/v1",
            api_key="k",
        )
        model = create_model(config)
        assert model.model == "openai/gemma4:31b"

    def test_factory_is_the_only_model_construction_point(self):
        """Guards against an adapter being bypassed by a second path."""
        import inspect

        from src.llm import factory

        source = inspect.getsource(factory)
        assert "Gemini(" not in source
        assert "LiteLlm(" not in source

    def test_stage_configs_resolve_to_concrete_models(self):
        from src.llm.model_configs import EDITOR_MODEL, OUTLINE_MODEL

        assert create_model(OUTLINE_MODEL) is not None
        assert create_model(EDITOR_MODEL) is not None

    def test_unsupported_provider_raises(self):
        config = _google_config()
        object.__setattr__(config, "provider", "cohere")
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_model(config)
