"""Diagnostic: print exact completion_args immediately before acompletion().

Run:  .venv/bin/python scripts/diagnose_response_format.py
Safe: makes no network calls (litellm.acompletion is monkeypatched to raise).

Historical note: this script existed to diagnose why ``output_schema`` was
being dropped on the Ollama path. Structured-output enforcement has since moved
out of ADK and into ``src.normalizer`` as explicit workflow nodes, so the
pipeline no longer sets a response schema. It is kept because the question it
asks — "what is actually sent to litellm?" — is still the right one to ask
before trusting any provider's structured-output behaviour.
"""

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import litellm
from google.adk.models.llm_request import LlmRequest

from src.llm.factory import create_model
from src.llm.model_configs import OUTLINE_MODEL


def _fake_acompletion(**completion_args):
    redacted = dict(completion_args)
    if redacted.get("api_key"):
        redacted["api_key"] = "***REDACTED***"
    print("=" * 78)
    print("COMPLETION_ARGS ACTUALLY PASSED TO litellm.acompletion()")
    print("=" * 78)
    print(json.dumps(redacted, indent=2, default=str))

    rf = completion_args.get("response_format")
    print("\n--- response_format verdict ---")
    if rf is None:
        print("response_format is ABSENT -> no structured output requested")
        return
    print("type            =", rf.get("type"))
    js = rf.get("json_schema") or {}
    print("json_schema.name  =", js.get("name"))
    print("json_schema.strict=", js.get("strict"))
    schema = js.get("schema") or {}
    print("root required     =", schema.get("required"))
    print("additionalProperties=", schema.get("additionalProperties"))
    print("$defs present     =", "$defs" in schema)
    raise SystemExit(0)


async def _main() -> None:
    litellm.acompletion = _fake_acompletion

    from src.agents.outline_agent import outline_agent

    request = LlmRequest(model=OUTLINE_MODEL.name)
    request.append_instructions(["Generate a structured blog outline."])

    model = create_model(OUTLINE_MODEL)
    print("model.canonical name     =", model.model)
    print("model.api_base           =", model._additional_args.get("api_base"))
    print("response_schema          =", request.config.response_schema)
    print("model.capabilities       =", outline_agent.canonical_model.capabilities)

    try:
        async for _ in outline_agent.canonical_model.generate_content_async(request):
            pass
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("unexpected:", type(exc).__name__, exc)


if __name__ == "__main__":
    asyncio.run(_main())
