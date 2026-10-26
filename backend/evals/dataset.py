"""Load and validate the small, versioned golden dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).with_name("dataset.json")


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    kind: str
    topic: str
    audience: str
    tone: str
    expected_tools: tuple[str, ...]
    expected_output: str | None = None
    expected_intent_clear: bool | None = None
    research: dict[str, Any] | None = None

    @property
    def prompt(self) -> str:
        return (
            f"Write a blog about {self.topic} for {self.audience} "
            f"in a {self.tone} tone."
        )


def load_dataset() -> tuple[str, list[GoldenCase]]:
    """Load goldens and fail early on incomplete or duplicate scenario records."""
    payload = json.loads(DATASET_PATH.read_text())
    version = str(payload["version"])
    cases = [
        GoldenCase(
            **{
                **record,
                "expected_tools": tuple(record.get("expected_tools", [])),
            }
        )
        for record in payload["cases"]
    ]
    if not cases:
        raise ValueError("The eval dataset must contain at least one golden case")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Golden case ids must be unique")
    for case in cases:
        if case.kind not in {"generate", "blocked"}:
            raise ValueError(f"Unsupported golden kind: {case.kind}")
        if case.kind == "generate" and (not case.expected_output or not case.research):
            raise ValueError(f"Generation golden {case.id!r} needs output and research references")
    return version, cases
