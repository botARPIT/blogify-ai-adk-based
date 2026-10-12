"""
Repeated Ollama Cloud structured-output reliability test.

Goal:
    Determine whether Ollama Cloud + gpt-oss:120b reliably follows the exact
    production OutlineSchema when given a strict JSON Schema.

Environment:
    LLM_API_KEY=...
    OLLAMA_BASE_URL=https://ollama.com/v1
    OLLAMA_MODEL=gpt-oss:120b

Optional:
    OLLAMA_TEST_RUNS=10
    OLLAMA_TEST_DELAY_SECONDS=1
    OLLAMA_TEST_MAX_COMPLETION_TOKENS=2048

Run:
    python test_ollama_outline_schema_reliability.py
"""

import asyncio
import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from jsonschema import Draft202012Validator
from litellm import acompletion
from pydantic import BaseModel, Field, ValidationError

load_dotenv()


class SectionSchema(BaseModel):
    """Production SectionSchema."""

    id: str = Field(description="Unique section identifier")
    heading: str = Field(description="Section heading")
    goal: str = Field(description="What this section should accomplish")
    target_words: int = Field(
        ge=80,
        le=300,
        description="Target word count",
    )


class OutlineSchema(BaseModel):
    """Production OutlineSchema."""

    title: str = Field(max_length=120, description="Blog title")
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


LLM_API_KEY = os.getenv("LLM_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

RUNS = int(os.getenv("OLLAMA_TEST_RUNS", "10"))
DELAY_SECONDS = float(os.getenv("OLLAMA_TEST_DELAY_SECONDS", "1"))
MAX_COMPLETION_TOKENS = int(
    os.getenv("OLLAMA_TEST_MAX_COMPLETION_TOKENS", "2048")
)

SYSTEM_PROMPT = """
Create a blog outline for the requested topic.

Return ONLY the JSON object matching the supplied schema.

Do not:
- use Markdown
- use code fences
- add commentary
- add text before or after the JSON

For every section:
- id MUST be a string, for example "sec1"
- heading MUST be a string
- goal MUST be a string
- target_words MUST be an integer between 80 and 300

The root object MUST contain:
- title
- sections
- estimated_total_words

Do NOT rename estimated_total_words to total_word_count.
"""


def build_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "OutlineSchema",
            "strict": True,
            "schema": OutlineSchema.model_json_schema(),
        },
    }


def json_schema_errors(data: Any) -> list[str]:
    validator = Draft202012Validator(OutlineSchema.model_json_schema())
    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )

    result = []
    for error in errors:
        location = ".".join(str(p) for p in error.absolute_path)
        result.append(f"{location}: {error.message}" if location else error.message)
    return result


def shape_issues(data: Any) -> list[str]:
    issues: list[str] = []

    if not isinstance(data, dict):
        return ["Root value is not an object."]

    expected_root = {"title", "sections", "estimated_total_words"}
    actual_root = set(data.keys())

    missing = expected_root - actual_root
    extra = actual_root - expected_root

    if missing:
        issues.append(f"Missing root fields: {sorted(missing)}")
    if extra:
        issues.append(f"Extra root fields: {sorted(extra)}")

    sections = data.get("sections")
    if not isinstance(sections, list):
        issues.append("sections is not an array.")
        return issues

    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            issues.append(f"sections[{i}] is not an object.")
            continue

        section_id = section.get("id")
        if not isinstance(section_id, str):
            issues.append(
                f"sections[{i}].id expected string, "
                f"got {type(section_id).__name__}: {section_id!r}"
            )

    return issues


async def run_once(
    run_number: int,
    response_format: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()

    result: dict[str, Any] = {
        "run": run_number,
        "status": "failed",
        "raw": None,
        "json_valid": False,
        "json_schema_valid": False,
        "pydantic_valid": False,
        "shape_issues": [],
        "schema_errors": [],
        "pydantic_errors": [],
        "exception": None,
        "elapsed_seconds": None,
    }

    try:
        response = await acompletion(
            model=f"openai/{OLLAMA_MODEL}",
            api_base=OLLAMA_BASE_URL,
            api_key=LLM_API_KEY,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Create an outline for a blog titled "
                        "'Building Reliable Redis-Backed AI Pipelines'."
                    ),
                },
            ],
            response_format=response_format,
            temperature=0,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )

        raw = response.choices[0].message.content or ""
        result["raw"] = raw

        try:
            parsed = json.loads(raw)
            result["json_valid"] = True
        except json.JSONDecodeError as exc:
            result["exception"] = f"JSONDecodeError: {exc}"
            return result

        result["shape_issues"] = shape_issues(parsed)

        errors = json_schema_errors(parsed)
        result["schema_errors"] = errors
        result["json_schema_valid"] = not errors

        try:
            OutlineSchema.model_validate(parsed)
            result["pydantic_valid"] = True
        except ValidationError as exc:
            result["pydantic_errors"] = exc.errors()

        if result["json_schema_valid"] and result["pydantic_valid"]:
            result["status"] = "passed"

    except Exception as exc:
        result["exception"] = f"{type(exc).__name__}: {exc}"

    finally:
        result["elapsed_seconds"] = round(
            time.perf_counter() - started,
            3,
        )

    return result


async def main() -> int:
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY is not set.")
        return 1

    if RUNS < 1:
        print("ERROR: OLLAMA_TEST_RUNS must be >= 1.")
        return 1

    response_format = build_response_format()

    print("=" * 80)
    print("Ollama Cloud + GPT-OSS Structured Output Reliability Test")
    print("=" * 80)
    print(f"Model:                 openai/{OLLAMA_MODEL}")
    print(f"Base URL:              {OLLAMA_BASE_URL}")
    print("API key:               loaded")
    print(f"Runs:                  {RUNS}")
    print("Temperature:           0")
    print(f"Delay:                 {DELAY_SECONDS}s")
    print(f"Max completion tokens:{MAX_COMPLETION_TOKENS}")
    print()
    print("Validation: JSON + JSON Schema + Pydantic")
    print()

    results: list[dict[str, Any]] = []

    for run_number in range(1, RUNS + 1):
        print("=" * 80)
        print(f"RUN {run_number}/{RUNS}")
        print("=" * 80)

        result = await run_once(run_number, response_format)
        results.append(result)

        print(f"Status:       {result['status']}")
        print(f"Elapsed:      {result['elapsed_seconds']}s")
        print(f"JSON:         {result['json_valid']}")
        print(f"JSON Schema:  {result['json_schema_valid']}")
        print(f"Pydantic:     {result['pydantic_valid']}")

        if result["shape_issues"]:
            print("\nShape issues:")
            for issue in result["shape_issues"]:
                print(f"  - {issue}")

        if result["schema_errors"]:
            print("\nJSON Schema errors:")
            for error in result["schema_errors"]:
                print(f"  - {error}")

        if result["pydantic_errors"]:
            print("\nPydantic errors:")
            for error in result["pydantic_errors"]:
                print(f"  - {error}")

        if result["exception"]:
            print("\nException:")
            print(f"  {result['exception']}")

        print("\nRAW OUTPUT:")
        print(result["raw"] if result["raw"] is not None else "<none>")

        if run_number < RUNS and DELAY_SECONDS > 0:
            await asyncio.sleep(DELAY_SECONDS)

    passed = sum(r["status"] == "passed" for r in results)
    failed = RUNS - passed
    json_passed = sum(r["json_valid"] for r in results)
    schema_passed = sum(r["json_schema_valid"] for r in results)
    pydantic_passed = sum(r["pydantic_valid"] for r in results)

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total runs:             {RUNS}")
    print(f"Fully valid:            {passed}/{RUNS}")
    print(f"Failed:                 {failed}/{RUNS}")
    print(f"Valid JSON:             {json_passed}/{RUNS}")
    print(f"Valid JSON Schema:      {schema_passed}/{RUNS}")
    print(f"Valid Pydantic model:   {pydantic_passed}/{RUNS}")
    print(f"Schema reliability:     {passed / RUNS:.1%}")

    if passed == RUNS:
        print()
        print("✅ All runs satisfied the exact production schema.")
        return 0

    print()
    print("❌ At least one run violated the exact production schema.")
    print()
    print("Failed runs:")
    for result in results:
        if result["status"] != "passed":
            reason = result["exception"] or "schema validation failure"
            print(f"  Run {result['run']}: {reason}")

    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
