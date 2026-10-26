"""A scripted, in-memory ADK model for workflow graph tests.

Behaviour is driven by the replies handed to the constructor, and each instance
counts its own calls. Tests bind one instance per agent by patching
``create_model`` in that agent's module, so no test ever has to guess which
agent is asking. No network, no fixtures, no external services: these tests
exercise the *graph*, not a provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class ScriptedLLM(BaseLlm):
    """Returns a fixed script, one entry per model call.

    A single ``str`` is returned on every call. A ``list`` is consumed one entry
    per call, which is how a writer/editor revision cycle is scripted; the last
    entry repeats once exhausted.
    """

    model: str = "scripted"
    replies: Any = ""
    prompt_tokens: int = 7
    completion_tokens: int = 5

    _calls: int = 0

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["scripted"]

    @property
    def call_count(self) -> int:
        return self._calls

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if isinstance(self.replies, list):
            index = min(self._calls, len(self.replies) - 1) if self.replies else 0
            text = self.replies[index] if self.replies else ""
        else:
            text = self.replies
        self._calls += 1

        yield LlmResponse(
            model_version="scripted-v1",
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=self.prompt_tokens,
                candidates_token_count=self.completion_tokens,
                total_token_count=self.prompt_tokens + self.completion_tokens,
            ),
        )


class ScriptedConfirmationLLM(BaseLlm):
    """Calls ``tool_name`` once, then answers with ``confirm_text``.

    Used to exercise the outline review pause: the first turn issues the tool
    call that raises the ADK confirmation, and once the confirmation has been
    answered the model replies with plain text.
    """

    model: str = "scripted-confirm"
    tool_name: str = "review_generated_outline"
    confirm_text: str = "Outline approved, continuing."
    call_id: str = "fc-review-1"

    _calls: int = 0

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["scripted-confirm"]

    @property
    def call_count(self) -> int:
        return self._calls

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        already_answered = any(
            getattr(part, "function_response", None) is not None
            for content in llm_request.contents or []
            for part in (content.parts or [])
        )

        if self._calls == 0 and not already_answered:
            self._calls += 1
            yield LlmResponse(
                model_version="scripted-v1",
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id=self.call_id, name=self.tool_name, args={}
                            )
                        )
                    ],
                ),
            )
            return

        self._calls += 1
        yield LlmResponse(
            model_version="scripted-v1",
            content=types.Content(role="model", parts=[types.Part(text=self.confirm_text)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=7,
                candidates_token_count=5,
                total_token_count=12,
            ),
        )


class ScriptedModels:
    """Bind a :class:`ScriptedLLM` to each agent module's ``create_model``.

    Usable either as a context manager or called directly::

        with ScriptedModels(monkeypatch, outline=...) as models: ...
        models = ScriptedModels(monkeypatch, outline=...)

    Resolves roles by convention (``intent`` -> ``src.agents.intent_agent``) and
    yields the role -> model mapping so a test can assert how often each stage
    ran.
    """

    def __init__(self, monkeypatch: Any, **roles_and_replies: Any):
        self._monkeypatch = monkeypatch
        self._roles = roles_and_replies
        self.models: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        for role, replies in self._roles.items():
            module = _module_for(role)
            if replies is None:
                continue
            model = ScriptedLLM(replies=replies)
            self.models[role] = model
            self._monkeypatch.setattr(module, "create_model", lambda _config, m=model: m)
        return self.models

    def __exit__(self, *_exc: Any) -> bool:
        return False


_MODULE_BY_ROLE = {
    "intent": "src.agents.intent_agent",
    "outline": "src.agents.outline_agent",
    "outline_review": "src.agents.outline_review_agent",
    "research": "src.agents.research_agent",
    "writer": "src.agents.writer_agent",
    "editor": "src.agents.editor_agent",
}


def _module_for(role: str) -> Any:
    import importlib

    return importlib.import_module(_MODULE_BY_ROLE[role])


def json_reply(**kwargs: Any) -> str:
    """Compact JSON, for agents whose output is expected to be JSON."""
    return json.dumps(kwargs)


VALID_OUTLINE_MARKDOWN = """**Title:** Test Blog

**Section 1: Opening**
* Goal: Introduce the topic
* Target Word Count: 120 words

**Section 2: Middle**
* Goal: Develop the argument
* Target Word Count: 130 words

**Section 3: Close**
* Goal: Wrap up
* Target Word Count: 120 words
"""

INTENT_OK = json_reply(status="CLEAR", message="Clear topic.")

RESEARCH_OK = json_reply(topic="t", summary="s", sources=[], total_sources=0)

DRAFT = "# Test Blog\n\nBody text."


def editor_review(*, approved: bool, feedback: str = "", blog: str = DRAFT) -> str:
    """An editor verdict payload."""
    return json_reply(
        approved=approved,
        feedback=feedback,
        final_blog=blog if approved else "",
        sources_section="Sources:\n[1] Example" if approved else "",
    )
