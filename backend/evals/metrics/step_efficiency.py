"""Trajectory metric: were the workflow's execution steps necessary?"""

from __future__ import annotations

import os
from typing import Any


def build_metric() -> Any:
    from deepeval.metrics import StepEfficiencyMetric

    return StepEfficiencyMetric(
        model=os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4.1"),
        threshold=0.7,
        include_reason=True,
    )
