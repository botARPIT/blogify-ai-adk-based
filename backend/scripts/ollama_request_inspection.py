"""
ADK -> LiteLlm -> Ollama Cloud request inspection test.

Purpose:
    Inspect the LlmRequest created by Google ADK when using:

        output_schema=OutlineSchema

    BEFORE LiteLlm sends the request to Ollama Cloud.

This answers:
    1. Does ADK populate response_mime_type?
    2. Does ADK populate response_schema?
    3. What exact schema does ADK put into the LlmRequest?
    4. Does LiteLlm/Ollama then return output that ADK can validate?

This test does NOT use:
    - Redis
    - RedisSessionService
    - the Blogify pipeline
    - production agents
    - tools/function calling

Environment:
    LLM_API_KEY=...
    OLLAMA_BASE_URL=https://ollama.com/v1
    OLLAMA_MODEL=gpt-oss:120b

Run:
    python test_adk_ollama_request_inspection.py
"""

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field


load_dotenv()


# ---------------------------------------------------------------------------
# Exact production schemas
# ---------------------------------------------------------------------------


class SectionSchema(BaseModel):
    """Blog section definition."""

    id: str = Field(description="Unique section identifier")
    heading: str = Field(description="Section heading")
    goal: str = Field(description="What this section should accomplish")
    target_words: int = Field(
        ge=80,
        le=300,
        description="Target word count",
    )


class OutlineSchema(BaseModel):
    """Blog outline structure."""

    title: str = Field(
        max_length=120,
        description="Blog title",
    )
    sections: list[SectionSchema] = Field(
        min_length=3,
        max_length=7,
        description="Blog sections",
    )
    estimated_total_words: int = Field(
        ge=300,
        le=2000,
        description="Total estimated words",
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LLM_API_KEY = os.getenv("LLM_API_KEY")
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "https://ollama.com/v1",
)
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "gpt-oss:120b",
)


INSTRUCTION = """
Create a blog outline for the requested topic.

Return ONLY a valid JSON object matching the provided output schema.

Do not use Markdown.
Do not wrap the JSON in code fences.
Do not add explanations.
Do not add any text before or after the JSON.
"""


# ---------------------------------------------------------------------------
# Request inspection callback
# ---------------------------------------------------------------------------


def inspect_model_request(
    callback_context: Any,
    llm_request: LlmRequest,
):
    """
    Inspect the exact LlmRequest prepared by ADK.

    IMPORTANT:
        This callback does NOT modify the request.
        Returning None allows ADK to continue normally.
    """

    print()
    print("=" * 80)
    print("ADK BEFORE_MODEL_CALLBACK")
    print("=" * 80)

    print(f"Model: {getattr(llm_request, 'model', None)!r}")

    config = getattr(llm_request, "config", None)

    if config is None:
        print("❌ llm_request.config is None")
        return None

    print()
    print("--- CONFIG TYPE ---")
    print(type(config))

    # The fields we care about most.
    print()
    print("--- STRUCTURED OUTPUT FIELDS ---")

    response_mime_type = getattr(
        config,
        "response_mime_type",
        None,
    )
    response_schema = getattr(
        config,
        "response_schema",
        None,
    )

    print(
        "response_mime_type =",
        repr(response_mime_type),
    )

    print(
        "response_schema type =",
        type(response_schema),
    )

    print(
        "response_schema present =",
        response_schema is not None,
    )

    # Print the actual schema, if available.
    if response_schema is not None:
        print()
        print("--- ADK RESPONSE SCHEMA ---")

        try:
            if hasattr(response_schema, "model_dump"):
                schema_dump = response_schema.model_dump(
                    mode="json",
                    exclude_none=True,
                )
            elif hasattr(response_schema, "to_json_dict"):
                schema_dump = response_schema.to_json_dict()
            elif isinstance(response_schema, dict):
                schema_dump = response_schema
            else:
                schema_dump = str(response_schema)

            if isinstance(schema_dump, dict):
                print(
                    json.dumps(
                        schema_dump,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(schema_dump)

        except Exception as exc:
            print("Could not serialize response_schema:")
            print(type(exc).__name__, exc)

    # Dump all config fields as a second-level diagnostic.
    print()
    print("--- FULL CONFIG ---")

    try:
        if hasattr(config, "model_dump"):
            config_dump = config.model_dump(
                mode="json",
                exclude_none=True,
            )
            print(
                json.dumps(
                    config_dump,
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(repr(config))

    except Exception as exc:
        print("Could not serialize config:")
        print(type(exc).__name__, exc)

    print("=" * 80)
    print("END ADK REQUEST INSPECTION")
    print("=" * 80)
    print()

    return None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


def build_agent() -> Agent:
    return Agent(
        name="outline_request_inspection_agent",
        model=LiteLlm(
            model=f"openai/{OLLAMA_MODEL}",
            api_base=OLLAMA_BASE_URL,
            api_key=LLM_API_KEY,
        ),
        instruction=INSTRUCTION,
        output_schema=OutlineSchema,
        output_key="outline",
        before_model_callback=inspect_model_request,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def main() -> int:
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY is not set.")
        return 1

    print("=" * 80)
    print("ADK -> LiteLlm -> Ollama Cloud Request Inspection")
    print("=" * 80)
    print(f"Model:      openai/{OLLAMA_MODEL}")
    print(f"Base URL:   {OLLAMA_BASE_URL}")
    print("API key:    loaded")
    print()
    print(f"google-adk: {get_package_version('google.adk')}")
    print(f"litellm:    {get_package_version('litellm')}")
    print()

    agent = build_agent()

    session_service = InMemorySessionService()

    app_name = "ollama_request_inspection"
    user_id = "test-user"

    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
    )

    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    user_message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    "Create an outline for a blog titled "
                    "'Building Reliable Redis-Backed AI Pipelines'."
                )
            )
        ],
    )

    print("Running ADK...")
    print()

    events = []

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=user_message,
        ):
            events.append(event)

    except Exception as exc:
        print()
        print("=" * 80)
        print("❌ ADK RUN FAILED")
        print("=" * 80)
        print(f"{type(exc).__name__}: {exc}")
        print()
        print(
            "The BEFORE_MODEL_CALLBACK output above is the important part "
            "for diagnosing structured-output translation."
        )
        return 1

    print()
    print("=" * 80)
    print("✅ ADK RUN COMPLETED")
    print("=" * 80)
    print(f"Events: {len(events)}")

    final_session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session.id,
    )

    if final_session is None:
        print("No final session found.")
        return 1

    print()
    print("--- output_key='outline' ---")

    outline = final_session.state.get("outline")

    if outline is None:
        print("❌ outline was not written to session state.")
    else:
        print(
            json.dumps(
                outline,
                indent=2,
                ensure_ascii=False,
            )
        )
        print()
        print("✅ ADK accepted OutlineSchema.")

    return 0


def get_package_version(module_name: str) -> str:
    """Best-effort package version lookup."""

    try:
        if module_name == "google.adk":
            from google.adk import version

            return getattr(version, "__version__", "unknown")

        if module_name == "litellm":
            import litellm

            return getattr(litellm, "__version__", "unknown")

    except Exception:
        pass

    return "unknown"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
