from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr

from google.adk.models import BaseLlm
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class FakeLLM(BaseLlm):
    """Deterministic, file-backed ADK model for agent and Redis workload tests.

    The model is intentionally stateless. Each response is selected from the
    request history, not from a process-global call counter, so one model
    instance can safely serve concurrent sessions in a load test.
    """

    model: str = "fake"
    stage: str
    scenario_name: str

    _scenario: dict[str, Any] = PrivateAttr()
    _fixture_root: Path = PrivateAttr()

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "allow",
    }

    def __init__(
        self,
        *,
        stage: str,
        scenario: dict[str, Any],
        fixture_root: str | Path,
    ) -> None:
        super().__init__(
            model="fake",
            stage=stage,
            scenario_name=str(scenario["name"]),
        )
        self._scenario = scenario
        self._fixture_root = Path(fixture_root)

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["fake"]

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        config = self._scenario["stages"].get(self.stage)
        if config is None:
            raise AssertionError(
                f"No fake LLM stage configured for {self.stage!r} "
                f"in scenario {self.scenario_name!r}"
            )

        completed_tool_calls = self._count_completed_tool_calls(
            llm_request,
            set(config.get("tool_names", [])),
        )
        steps = config.get("steps", [])
        if not steps:
            raise AssertionError(f"No response steps configured for stage={self.stage!r}")

        step_index = min(completed_tool_calls, len(steps) - 1)
        step = steps[step_index]

        parts: list[types.Part] = []

        thought_text = self._load_text(step.get("thought_file"))
        if thought_text is None and step.get("thought_bytes", 0):
            thought_text = "t" * int(step["thought_bytes"])
        if thought_text:
            parts.append(types.Part(text=thought_text, thought=True))

        response_text = self._load_response_text(step)
        if response_text is not None:
            parts.append(types.Part(text=response_text))

        for call in step.get("tool_calls", []):
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=call.get("id") or f"fake-{self.stage}-{step_index}",
                        name=call["name"],
                        args=call.get("args", {}),
                    )
                )
            )

        prompt_tokens = int(step.get("prompt_tokens", 0))
        completion_tokens = int(step.get("completion_tokens", 0))
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
            total_token_count=prompt_tokens + completion_tokens,
        )

        yield LlmResponse(
            model_version=str(step.get("model_version", "fake-llm")),
            content=types.Content(role="model", parts=parts),
            usage_metadata=usage,
            custom_metadata={
                "fake_llm": True,
                "scenario": self.scenario_name,
                "stage": self.stage,
                "step_index": step_index,
            },
        )

    def _load_response_text(self, step: dict[str, Any]) -> str | None:
        response_file = step.get("response_file")
        if response_file:
            return json.dumps(
                json.loads((self._fixture_root / response_file).read_text()),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        return step.get("text")

    def _load_text(self, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        return (self._fixture_root / relative_path).read_text()

    @staticmethod
    def _count_completed_tool_calls(
        llm_request: LlmRequest,
        own_tool_names: set[str],
    ) -> int:
        count = 0
        for content in llm_request.contents or []:
            for part in content.parts or []:
                response = getattr(part, "function_response", None)
                if response is None:
                    continue
                name = getattr(response, "name", None)
                if not own_tool_names or name in own_tool_names:
                    count += 1
        return count


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Load one deterministic workload definition."""
    return json.loads(Path(path).read_text())