"""Run all golden cases through the pipeline and the selected DeepEval metrics.

Usage from ``backend/``::

    RUN_DEEPEVAL_EVALS=1 python -m evals.full_eval
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from evals.dataset import GoldenCase, load_dataset
from evals.metrics import (
    answer_correctness,
    argument_correctness,
    groundedness,
    step_efficiency,
    task_completion,
    tool_correctness,
)
from evals.pipeline import PipelineExecution, run_case, tool_calls_from_events
from evals.trace_adapter import record_adk_event


def _make_trace_runner():
    from deepeval.tracing import observe, update_current_span

    @observe()
    async def traced_run(case: GoldenCase) -> PipelineExecution:
        execution = await run_case(case)
        result = execution.result
        output = result.final_content or str(result.intent_result or "")
        update_current_span(input=case.prompt, output=output)
        for event in execution.events:
            await record_adk_event(event)
        return execution

    return traced_run


def _test_case(case: GoldenCase, execution: PipelineExecution) -> Any:
    from deepeval.test_case import LLMTestCase, ToolCall

    result = execution.result
    return LLMTestCase(
        input=case.prompt,
        actual_output=result.final_content,
        expected_output=case.expected_output,
        retrieval_context=[
            f"{source['title']}: {source['content']}"
            for source in (result.research or {}).get("sources", [])
        ],
        tools_called=[
            ToolCall(name=call["name"], input_parameters=call["input_parameters"])
            for call in tool_calls_from_events(execution.events)
        ],
        expected_tools=[ToolCall(name=name) for name in case.expected_tools],
    )


async def run_full_eval() -> None:
    if os.getenv("RUN_DEEPEVAL_EVALS") != "1":
        raise SystemExit("Set RUN_DEEPEVAL_EVALS=1 to run provider and judge calls")

    from deepeval import assert_test
    from deepeval.dataset import Golden

    version, cases = load_dataset()
    print(f"Running Blogify golden dataset v{version} ({len(cases)} cases)")
    traced_run = _make_trace_runner()

    for case in cases:
        execution = await traced_run(case)
        if case.kind == "blocked":
            if case.expected_intent_clear is not False:
                raise AssertionError(f"{case.id}: blocked golden must expect a false intent gate")
            print(f"PASS deterministic gate: {case.id}")
            continue

        golden = Golden(input=case.prompt, expected_output=case.expected_output)
        assert_test(
            golden=golden,
            metrics=[task_completion.build_metric(), step_efficiency.build_metric()],
        )
        test_case = _test_case(case, execution)
        assert_test(
            test_case,
            metrics=[answer_correctness.build_metric(), groundedness.build_metric()],
        )
        assert_test(
            test_case,
            metrics=[tool_correctness.build_metric(), argument_correctness.build_metric()],
        )
        print(f"PASS judged pipeline case: {case.id}")


def main() -> None:
    asyncio.run(run_full_eval())


if __name__ == "__main__":
    main()
