"""
Direct LiteLLM -> Ollama Cloud strict JSON-schema test.

Purpose:
    Test whether Ollama Cloud + gpt-oss:120b can produce output that
    conforms to the exact production OutlineSchema/SectionSchema contract.

This test does NOT use:
    - Google ADK
    - Redis
    - your Blogify pipeline

Environment:
    LLM_API_KEY=...
    OLLAMA_BASE_URL=https://ollama.com/v1
    OLLAMA_MODEL=gpt-oss:120b

Run:
    python test_ollama_outline_json_schema.py
"""

import asyncio
import json
import os

from dotenv import load_dotenv
from litellm import acompletion
from pydantic import BaseModel, Field, ValidationError

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


SYSTEM_PROMPT = """
Create a blog outline for the requested topic.

Follow the supplied JSON schema exactly.

Important:
- Return only the JSON object.
- Do not use Markdown.
- Do not wrap the response in ```json fences.
- Every section.id MUST be a JSON string, not a number.
- Every section must contain:
  id, heading, goal, target_words.
- target_words must be between 80 and 300.
- There must be between 3 and 7 sections.
- estimated_total_words must be between 300 and 2000.
"""


def build_response_format() -> dict:
    """
    Build an OpenAI-compatible strict JSON-schema response_format from
    the exact Pydantic production schema.
    """

    schema = OutlineSchema.model_json_schema()

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "OutlineSchema",
            "strict": True,
            "schema": schema,
        },
    }


async def main() -> int:
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY is not set.")
        return 1

    print("=" * 80)
    print("Ollama Cloud + GPT-OSS Strict JSON Schema Test")
    print("=" * 80)
    print(f"Model:      openai/{OLLAMA_MODEL}")
    print(f"Base URL:   {OLLAMA_BASE_URL}")
    print("API key:    loaded")
    print()

    response_format = build_response_format()

    print("JSON Schema sent to model:")
    print(json.dumps(response_format, indent=2, ensure_ascii=False))
    print()

    try:
        response = await acompletion(
            model=f"openai/{OLLAMA_MODEL}",
            api_base=OLLAMA_BASE_URL,
            api_key=LLM_API_KEY,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        "Create an outline for a blog titled "
                        "'Building Reliable Redis-Backed AI Pipelines'."
                    ),
                },
            ],
            response_format=response_format,
        )
    except Exception as exc:
        print("=" * 80)
        print("❌ MODEL CALL FAILED")
        print("=" * 80)
        print(f"{type(exc).__name__}: {exc}")
        return 1

    raw = response.choices[0].message.content or ""

    print("=" * 80)
    print("RAW MODEL OUTPUT")
    print("=" * 80)
    print(raw)
    print()

    # -----------------------------------------------------------------------
    # Test 1: JSON syntax
    # -----------------------------------------------------------------------

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("=" * 80)
        print("❌ JSON TEST FAILED")
        print("=" * 80)
        print(f"json.loads() failed: {exc}")
        return 1

    print("✅ Valid JSON")

    # -----------------------------------------------------------------------
    # Test 2: exact Pydantic schema
    # -----------------------------------------------------------------------

    print()
    print("=" * 80)
    print("PYDANTIC VALIDATION")
    print("=" * 80)

    try:
        outline = OutlineSchema.model_validate(parsed)
    except ValidationError as exc:
        print("❌ OutlineSchema validation FAILED")
        print(exc)
        return 1

    print("✅ OutlineSchema validation PASSED")
    print()
    print(outline.model_dump_json(indent=2, ensure_ascii=False))

    # -----------------------------------------------------------------------
    # Explicit type diagnostics for section IDs
    # -----------------------------------------------------------------------

    print()
    print("=" * 80)
    print("SECTION ID TYPE CHECK")
    print("=" * 80)

    for index, section in enumerate(parsed.get("sections", [])):
        section_id = section.get("id")
        print(
            f"sections[{index}].id = {section_id!r} "
            f"(Python type: {type(section_id).__name__})"
        )

        if not isinstance(section_id, str):
            print("❌ Section ID is not a string")
            return 1

    print("✅ All section IDs are strings")

    # -----------------------------------------------------------------------
    # Metadata
    # -----------------------------------------------------------------------

    print()
    print("=" * 80)
    print("RESPONSE METADATA")
    print("=" * 80)
    print(f"finish_reason: {response.choices[0].finish_reason}")

    usage = getattr(response, "usage", None)
    if usage is not None:
        print(f"usage: {usage}")

    print()
    print("=" * 80)
    print("✅ TEST PASSED")
    print("=" * 80)
    print(
        "Ollama Cloud returned JSON that conforms to the exact "
        "production OutlineSchema."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
