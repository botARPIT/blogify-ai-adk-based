"""Transport adapters.

An adapter owns *how* to connect to a model. It never decides *which* model to
use (that is :mod:`src.llm.model_configs`) and it never contains model-specific
branches — only transport-level translation.

The factory (:mod:`src.llm.factory`) selects an adapter from
``ModelConfig.provider``.
"""

from src.llm.adapters.google import create_google_model
from src.llm.adapters.litellm import build_litellm_kwargs, create_litellm_model

__all__ = [
    "build_litellm_kwargs",
    "create_google_model",
    "create_litellm_model",
]
