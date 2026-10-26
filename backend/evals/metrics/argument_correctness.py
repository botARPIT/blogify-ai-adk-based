"""Evaluate whether research tool arguments match the requested topic."""

from __future__ import annotations

import os
from typing import Any


def build_metric() -> Any:
    from deepeval.metrics import ArgumentCorrectnessMetric

    return ArgumentCorrectnessMetric(
        model=os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4.1"),
        threshold=0.8,
        include_reason=True,
    )
