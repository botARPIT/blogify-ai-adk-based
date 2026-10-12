"""
Nemotron 3 Ultra -> Ollama Cloud integration/reliability test.

This test intentionally bypasses LiteLLM. The purpose is to answer:

1. Is `nemotron-3-ultra:cloud` reachable through Ollama Cloud?
2. What does it return when asked for our exact OutlineSchema?
3. Does Ollama Cloud accept/enforce JSON Schema?
4. If schema mode is unavailable, does plain JSON mode work well enough
   for us to validate with Pydantic ourselves?

Run from the Blogify backend root:

    export LLM_API_KEY="..."
    python tests/test_nemotron_ollama_cloud.py

Optional:
    NEMOTRON_TEST_CALLS=5
    NEMOTRON_TEST_MAX_TOKENS=2000
    NEMOTRON_TEST_MODE=schema
    NEMOTRON_TEST_MODE=json

Modes:
    schema -> request strict JSON Schema
    json   -> request JSON object mode

If NEMOTRON_TEST_MODE is not set, BOTH modes are tested.

IMPORTANT
---------
This uses the OpenAI-compatible Ollama Cloud endpoint directly:

    https://ollama.com/v1

and the real Ollama model identifier:

    nemotron-3-ultra:cloud

There is deliberately NO `openai/` prefix in the model name here.
That prefix is only a LiteLLM routing implementation detail and is not
part of the Ollama model identifier.

The test uses Blogify's exact production OutlineSchema.
"""

from __future__ import annotations

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.models.schemas import OutlineSchema


API_BASE = os.getenv("OLLAMA_API_BASE", "https://ollama.com/v1")
API_KEY = os.getenv("LLM_API_KEY")
MODEL = os.getenv("NEMOTRON_TEST_MODEL", "nemotron-3-ultra:cloud")

CALLS = int(os.getenv("NEMOTRON_TEST_CALLS", "5"))
MAX_TOKENS = int(
    os.getenv("NEMOTRON_TEST_MAX_TOKENS", "2000")
)
TEMPERATURE = float(
    os.getenv("NEMOTRON_TEST_TEMPERATURE", "0")
)

MODES = {
    "schema",
    "json",
}

requested_mode = os.getenv("NEMOTRON_TEST_MODE", "both").lower()

if requested_mode == "both":
    TEST_MODES = ["schema", "json"]
elif requested_mode in MODES:
    TEST_MODES = [requested_mode]
else:
    raise SystemExit(
        "NEMOTRON_TEST_MODE must be one of: schema, json, both"
    )


PROMPT = """
Create a detailed blog outline for:
"How Redis helps build reliable background job systems"

Audience: backend engineers with 1–3 years of experience.

Requirements:
- Give the blog a clear, practical title.
- Use 3 to 7 sections.
- Give every section a concrete goal.
- Give every section a realistic target word count between 80 and 300.
- Return only the requested structured output.
""".strip()


@dataclass
class Result:
    mode: str
    call: int
    latency: float
    success: bool
    category: str | None = None
    detail: str | None = None
    raw: str | None = None


def build_schema() -> dict[str, Any]:
    return OutlineSchema.model_json_schema()


def validate_outline(content: str) -> None:
    payload = json.loads(content)

    if not isinstance(payload, dict):
        raise ValueError(
            f"top_level_not_object: {type(payload).__name__}"
        )

    OutlineSchema.model_validate(payload)


def build_request_kwargs(mode: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
            }
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }

    if mode == "schema":
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "OutlineSchema",
                "strict": True,
                "schema": build_schema(),
            },
        }

    elif mode == "json":
        kwargs["response_format"] = {
            "type": "json_object",
        }

    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return kwargs


async def run_one(
    client: AsyncOpenAI,
    mode: str,
    call: int,
) -> Result:
    started = time.perf_counter()

    try:
        response = await client.chat.completions.create(
            **build_request_kwargs(mode)
        )

        latency = time.perf_counter() - started
        content = response.choices[0].message.content

        if content is None:
            return Result(
                mode=mode,
                call=call,
                latency=latency,
                success=False,
                category="empty_response",
            )

        if not isinstance(content, str):
            content = str(content)

        try:
            validate_outline(content)
        except json.JSONDecodeError as exc:
            return Result(
                mode=mode,
                call=call,
                latency=latency,
                success=False,
                category="invalid_json",
                detail=str(exc),
                raw=content,
            )
        except ValidationError as exc:
            details = []

            for error in exc.errors():
                location = ".".join(
                    str(part) for part in error["loc"]
                )
                details.append(
                    f"{location}: {error['type']}"
                )

            return Result(
                mode=mode,
                call=call,
                latency=latency,
                success=False,
                category="schema_validation",
                detail="; ".join(details),
                raw=content,
            )
        except ValueError as exc:
            return Result(
                mode=mode,
                call=call,
                latency=latency,
                success=False,
                category="shape_error",
                detail=str(exc),
                raw=content,
            )

        return Result(
            mode=mode,
            call=call,
            latency=latency,
            success=True,
            raw=content,
        )

    except Exception as exc:
        return Result(
            mode=mode,
            call=call,
            latency=time.perf_counter() - started,
            success=False,
            category="request_error",
            detail=f"{type(exc).__name__}: {exc}",
        )


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round(0.95 * len(ordered))) - 1),
    )
    return ordered[index]


def print_mode_report(
    mode: str,
    results: list[Result],
) -> None:
    passed = sum(result.success for result in results)
    latencies = [result.latency for result in results]

    failures = Counter(
        result.category
        for result in results
        if not result.success
    )

    print("\n" + "-" * 72)
    print(f"MODE: {mode.upper()}")
    print("-" * 72)
    print(
        f"Schema pass rate: "
        f"{passed}/{len(results)} "
        f"({passed / len(results) * 100:.1f}%)"
    )
    print(
        f"Mean latency:     "
        f"{statistics.mean(latencies):.2f}s"
    )
    print(
        f"Median latency:   "
        f"{statistics.median(latencies):.2f}s"
    )
    print(
        f"Approx p95:       "
        f"{percentile_95(latencies):.2f}s"
    )

    if failures:
        print("\nFailures:")
        for category, count in failures.most_common():
            print(f"  {category}: {count}")

    print("\nCalls:")
    for result in results:
        status = "PASS" if result.success else "FAIL"

        suffix = ""
        if not result.success:
            suffix = (
                f" [{result.category}]"
                f" {result.detail or ''}"
            )

        print(
            f"  [{status}] "
            f"call={result.call:02d} "
            f"latency={result.latency:.2f}s"
            f"{suffix}"
        )

        if not result.success and result.raw:
            preview = result.raw[:1400].replace(
                "\n",
                "\n      ",
            )
            print(f"      output: {preview}")


async def main() -> None:
    if not API_KEY:
        raise SystemExit(
            "LLM_API_KEY is not set. "
            "Export the Ollama Cloud API key first."
        )

    if CALLS <= 0:
        raise SystemExit(
            "NEMOTRON_TEST_CALLS must be greater than 0."
        )

    client = AsyncOpenAI(
        base_url=API_BASE,
        api_key=API_KEY,
    )

    print("=" * 72)
    print("NEMOTRON 3 ULTRA — OLLAMA CLOUD TEST")
    print("=" * 72)
    print(f"Model:       {MODEL}")
    print(f"Endpoint:    {API_BASE}")
    print(f"Calls/mode:  {CALLS}")
    print(f"Temperature: {TEMPERATURE}")
    print(f"Max tokens:  {MAX_TOKENS}")
    print(f"Modes:       {', '.join(TEST_MODES)}")
    print()
    print(
        "Note: Ollama currently lists Nemotron 3 Ultra as a high-usage "
        "cloud model, so keep the call count intentionally small."
    )

    all_results: dict[str, list[Result]] = {}

    for mode in TEST_MODES:
        print(f"\nRunning {mode} mode...")

        results: list[Result] = []

        # Sequential calls are deliberate. This is a reliability test,
        # not a throughput test, and Ollama's Free tier is concurrency-limited.
        for call in range(1, CALLS + 1):
            result = await run_one(client, mode, call)
            results.append(result)

        all_results[mode] = results
        print_mode_report(mode, results)

    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)

    for mode, results in all_results.items():
        passed = sum(result.success for result in results)
        total = len(results)
        rate = passed / total * 100

        request_errors = sum(
            result.category == "request_error"
            for result in results
        )

        print(
            f"{mode:<8} "
            f"pass={passed}/{total} "
            f"rate={rate:>5.1f}% "
            f"request_errors={request_errors}"
        )

    print()
    print("Interpretation:")
    print(
        "  PASS means the response was valid JSON and also satisfied "
        "Blogify's exact OutlineSchema."
    )
    print(
        "  schema_validation means JSON was produced but it violated "
        "the application contract."
    )
    print(
        "  invalid_json means the model returned non-JSON content."
    )
    print(
        "  request_error means the request itself failed; do not treat "
        "that as model-output quality."
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
