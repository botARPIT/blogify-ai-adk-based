"""Reference-based correctness for the final generated blog."""

from __future__ import annotations

import os
from typing import Any


def build_metric() -> Any:
    from deepeval.metrics import GEval
    from deepeval.test_case import SingleTurnParams

    return GEval(
        name="BlogAnswerCorrectness",
        model=os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4.1"),
        threshold=0.7,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        evaluation_steps=[
            "Compare the blog with the expected answer requirements.",
            "Check central facts, audience fit, and whether the output addresses the requested topic.",
            "Penalize contradictions, unsupported guarantees, or missing key requirements while allowing reasonable wording differences.",
        ],
        include_reason=True,
    )
