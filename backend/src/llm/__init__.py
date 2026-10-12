"""Provider-agnostic LLM construction for ADK agents.

Usage::

    from src.llm.factory import create_model
    from src.llm.model_configs import OUTLINE_MODEL

    model = create_model(OUTLINE_MODEL)

Application code names models the way the provider does (``gemma4:31b``). Any
client-library routing prefix is added by the adapter, not by the caller.
"""

from src.llm.config import LLMProvider, LLMTransport, ModelConfig
from src.llm.factory import create_model

__all__ = [
    "LLMProvider",
    "LLMTransport",
    "ModelConfig",
    "create_model",
]
