"""LiteLLM adapter contract.

The adapter is the translation boundary between application configuration and
LiteLLM. It is also the guard that keeps an OpenAI-compatible transport from
being routed onto Ollama's native ``/api/generate`` dialect.
"""

from __future__ import annotations

import pytest
from google.adk.models.lite_llm import LiteLlm

from src.llm.adapters.litellm import (
    build_litellm_kwargs,
    create_litellm_model,
    to_litellm_model_name,
)
from src.llm.config import LLMProvider, LLMTransport, ModelConfig


def _config(**overrides) -> ModelConfig:
    base = {
        "provider": LLMProvider.OLLAMA,
        "transport": LLMTransport.OPENAI_COMPATIBLE,
        "name": "gemma4:31b",
        "api_base": "https://ollama.com/v1",
        "api_key": "test-key",
        "temperature": 0.3,
        "max_output_tokens": 2000,
        "retry_attempts": 3,
    }
    base.update(overrides)
    return ModelConfig(**base)


class TestModelNameTranslation:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("gemma4:31b", "openai/gemma4:31b"),
            ("gpt-oss:120b", "openai/gpt-oss:120b"),
            ("llama3:70b", "openai/llama3:70b"),
        ],
    )
    def test_provider_native_name_is_prefixed_for_litellm(self, name, expected):
        assert to_litellm_model_name(_config(name=name)) == expected

    def test_already_prefixed_name_is_left_alone(self):
        assert to_litellm_model_name(_config(name="azure/gpt-4o")) == "azure/gpt-4o"

    def test_kwargs_model_field_is_the_translated_name(self):
        kwargs = build_litellm_kwargs(_config(name="gemma4:31b"))
        assert kwargs["model"] == "openai/gemma4:31b"


class TestParameterMapping:
    def test_retry_attempts_map_to_litellm_num_retries(self):
        kwargs = build_litellm_kwargs(_config(retry_attempts=7))
        assert kwargs["num_retries"] == 7

    def test_max_output_tokens_map_to_litellm_token_parameter(self):
        kwargs = build_litellm_kwargs(_config(max_output_tokens=4096))
        assert kwargs["max_completion_tokens"] == 4096
        assert "max_tokens" not in kwargs

    def test_unbounded_output_omits_token_parameter(self):
        kwargs = build_litellm_kwargs(_config(max_output_tokens=None))
        assert "max_completion_tokens" not in kwargs
        assert "max_tokens" not in kwargs

    def test_request_params_are_merged(self):
        kwargs = build_litellm_kwargs(
            _config(request_params={"extra_body": {"include_reasoning": False}})
        )
        assert kwargs["extra_body"] == {"include_reasoning": False}

    def test_temperature_and_credentials_pass_through(self):
        kwargs = build_litellm_kwargs(_config(temperature=0.11, api_key="k"))
        assert kwargs["temperature"] == 0.11
        assert kwargs["api_key"] == "k"


class TestEndpointIsNeverGuessed:
    """Regression guard for the `https://ollama.com/v1/api/generate` failure."""

    def test_api_base_is_forwarded_verbatim(self):
        kwargs = build_litellm_kwargs(_config(api_base="https://ollama.com/v1"))
        assert kwargs["api_base"] == "https://ollama.com/v1"

    def test_missing_api_base_is_refused_rather_than_inferred(self):
        with pytest.raises(ValueError, match="api_base is required"):
            build_litellm_kwargs(_config(api_base=None))

    def test_ollama_native_transport_is_refused(self):
        with pytest.raises(ValueError, match="openai_compatible"):
            build_litellm_kwargs(_config(transport=LLMTransport.OLLAMA_NATIVE))

    def test_google_native_transport_is_refused(self):
        with pytest.raises(ValueError, match="openai_compatible"):
            build_litellm_kwargs(
                _config(provider=LLMProvider.GOOGLE, transport=LLMTransport.GOOGLE_NATIVE)
            )


class TestAdapterContainsNoModelBranching:
    def test_adapter_source_has_no_model_name_conditionals(self):
        """Model-specific behaviour must not leak into the transport layer.

        Checks executable code only: docstrings legitimately mention model names
        to explain the rule.
        """
        import ast
        import inspect

        from src.llm.adapters import litellm

        tree = ast.parse(inspect.getsource(litellm))
        model_names = ("gpt-oss", "gemma4", "gemini-", "llama3")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in model_names:
                    pytest.fail(
                        f"Adapter hardcodes model identity {node.value!r}; model "
                        "choices belong in src.llm.model_configs."
                    )

    def test_adapter_has_no_name_equality_comparison(self):
        import ast
        import inspect

        from src.llm.adapters import litellm

        tree = ast.parse(inspect.getsource(litellm))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq):
                operands = [node.left, *node.comparators]
                attr_names = {o.attr for o in operands if isinstance(o, ast.Attribute)}
                assert "name" not in attr_names


class TestModelConstruction:
    def test_builds_a_litellm_model(self):
        model = create_litellm_model(_config())
        assert isinstance(model, LiteLlm)
        assert model.model == "openai/gemma4:31b"

    def test_constructed_model_keeps_openai_compatible_base(self):
        model = create_litellm_model(_config())
        assert model._additional_args["api_base"] == "https://ollama.com/v1"

    def test_model_specific_extra_body_reaches_the_client(self):
        model = create_litellm_model(
            _config(
                name="gpt-oss:120b",
                request_params={"extra_body": {"include_reasoning": False}},
            )
        )
        assert model._additional_args["extra_body"] == {"include_reasoning": False}
