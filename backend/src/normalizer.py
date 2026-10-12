"""Deterministic normalization of raw model output into application data.

An ADK agent emits whatever text the model produced. With provider-dependent
structured-output enforcement removed from the agents, that text is Markdown or
JSON depending on the model and the prompt. This module is the single boundary
that turns it into validated application data.

Responsibilities::

    raw LLM output
        ↓
    detect representation
        ↓
    JSON → parse      /      Markdown → parse
        ↓
    construct application payload
        ↓
    Schema.model_validate()
        ↓
    validated domain object

What it deliberately does **not** do: call a model, retry, touch Redis or
Postgres, reach into ADK runner internals, or make workflow decisions. It is a
pure function of its input.

Representation vs. semantics
----------------------------
Normalization fixes *representation*: ``### Section 1 – Foo`` becomes the field
``heading``. It never repairs *meaning*. A field named ``total_word_count`` is
not silently rewritten to ``estimated_total_words``; the mismatch stays visible
as a validation failure. Guessing what the model "meant" would hide exactly the
kind of drift this boundary exists to surface.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.models.schemas import EditorReviewSchema, IntentSchema, OutlineSchema

_ModelT = TypeVar("_ModelT", bound=BaseModel)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NormalizationError(ValueError):
    """Raw model output could not be turned into valid application data.

    Carries enough context to locate the failure without reading the raw text:
    which workflow and stage produced it, which agent emitted it, what
    representation was detected, and which field paths failed validation.
    """

    def __init__(
        self,
        *,
        stage: str,
        agent: str,
        reason: str,
        output_format: str = "unknown",
        field_paths: list[str] | None = None,
        workflow: str = "unknown",
    ) -> None:
        self.stage = stage
        self.agent = agent
        self.reason = reason
        self.output_format = output_format
        self.field_paths = list(field_paths or [])
        self.workflow = workflow
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [
            f"workflow={self.workflow}",
            f"stage={self.stage}",
            f"agent={self.agent}",
            f"format={self.output_format}",
            f"reason={self.reason}",
        ]
        if self.field_paths:
            parts.append(f"fields={','.join(self.field_paths)}")
        return "normalization failed | " + " | ".join(parts)


# ---------------------------------------------------------------------------
# Raw output extraction
# ---------------------------------------------------------------------------


def extract_raw_output(node_input: Any) -> str:
    """Reduce whatever a predecessor node produced to a raw text string.

    A workflow node's input is the predecessor's ``ctx.output``. For an LLM
    agent that is the model's text, but the contract permits any value, so this
    collapses the shapes that can occur and nothing else. Keeping the collapse
    in one place is the point: no other module should be reaching into ADK node
    output to find text.
    """
    if node_input is None:
        return ""

    if isinstance(node_input, str):
        return node_input

    if isinstance(node_input, bytes):
        return node_input.decode("utf-8", errors="replace")

    # ADK delivers a model's reply as ``Content``, which is itself a pydantic
    # model and must be unwrapped here rather than serialized as JSON. A node's
    # result is an ``Event`` wrapping such a ``Content`` under ``.content``.
    # Both carry their text in ``parts``.
    parts = getattr(node_input, "parts", None)
    if parts is None:
        parts = getattr(getattr(node_input, "content", None), "parts", None)
    if parts is not None:
        return "".join(part.text for part in parts if getattr(part, "text", None))

    if isinstance(node_input, BaseModel):
        return node_input.model_dump_json()

    if isinstance(node_input, (dict, list)):
        return json.dumps(node_input)

    return str(node_input)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FENCE = re.compile(
    r"```(?:json|JSON)?\s*(?P<body>.*?)\s*```",
    re.DOTALL,
)


def _strip_fences(text: str) -> str:
    """Return the contents of the first fenced block, or the text unchanged."""
    match = _FENCE.search(text)
    return match.group("body").strip() if match else text.strip()


def _field_paths(exc: ValidationError) -> list[str]:
    """Flatten a pydantic error into dotted field paths."""
    paths = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        paths.append(location or "<root>")
    return paths


def _validate(
    schema: type[_ModelT], payload: Any, *, stage: str, agent: str, output_format: str
) -> _ModelT:
    """Run ``payload`` through ``schema`` or raise a located failure."""
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise NormalizationError(
            workflow="blog_generation",
            stage=stage,
            agent=agent,
            output_format=output_format,
            reason=exc.errors()[0].get("msg", "schema validation failed"),
            field_paths=_field_paths(exc),
        ) from exc


def _as_int(value: Any) -> int | None:
    """Parse a word count written as a number or a numeric phrase."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    if not isinstance(value, str):
        return None

    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _required(payload: dict[str, Any], *names: str) -> tuple[Any, ...] | None:
    """Return the named values, or ``None`` if any is absent."""
    values = []
    for name in names:
        if name not in payload:
            return None
        value = payload[name]
        if value is None or value == "":
            return None
        values.append(value)
    return tuple(values)


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------


def normalize_intent(raw_output: str) -> IntentSchema:
    """Convert raw intent-classifier output into :class:`IntentSchema`."""
    text = _strip_fences(raw_output)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NormalizationError(
            workflow="blog_generation",
            stage="intent",
            agent="intent_classifier",
            output_format="text",
            reason=f"expected a JSON object: {exc.msg}",
        ) from exc

    if not isinstance(payload, dict):
        raise NormalizationError(
            workflow="blog_generation",
            stage="intent",
            agent="intent_classifier",
            output_format="json",
            reason=f"expected a JSON object, got {type(payload).__name__}",
        )

    return _validate(
        IntentSchema, payload, stage="intent", agent="intent_classifier", output_format="json"
    )


# ---------------------------------------------------------------------------
# Editor review
# ---------------------------------------------------------------------------


def normalize_editor_review(raw_output: str) -> EditorReviewSchema:
    """Convert raw editor output into :class:`EditorReviewSchema`."""
    text = _strip_fences(raw_output)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NormalizationError(
            workflow="blog_generation",
            stage="editor",
            agent="editor_agent",
            output_format="text",
            reason=f"expected a JSON object: {exc.msg}",
        ) from exc

    if not isinstance(payload, dict):
        raise NormalizationError(
            workflow="blog_generation",
            stage="editor",
            agent="editor_agent",
            output_format="json",
            reason=f"expected a JSON object, got {type(payload).__name__}",
        )

    return _validate(
        EditorReviewSchema,
        payload,
        stage="editor",
        agent="editor_agent",
        output_format="json",
    )


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?P<text>.+?)\s*#*\s*$")
_BOLD_LINE = re.compile(r"^\s*\*\*(?P<text>.+?)\*\*\s*:?\s*$")
_BOLD_INLINE = re.compile(r"^\s*\*\*(?P<label>[^*:]+?)\s*:\s*\*\*\s*(?P<value>.+?)\s*$")
_BULLET = re.compile(r"^\s*[*+-]\s*(?P<text>.+?)\s*$")
_LABELLED = re.compile(
    r"^\s*(?:[*+-]\s*)?(?:\*\*|__)?\s*(?P<label>[A-Za-z][A-Za-z _]{2,30}?)\s*(?:\*\*|__)?\s*:\s*(?P<value>.+?)\s*$"
)

_SECTION_PREFIX = re.compile(r"^section\s*(?P<number>\d+)\s*[.:)\-–—]?\s*", re.IGNORECASE)
_RANGE = re.compile(r"(\d[\d,]*)\s*(?:[–—\-~]|to)\s*(\d[\d,]*)")

_TITLE_LABELS = {"title", "blog title"}
_GOAL_LABELS = {"goal", "objective", "purpose", "focus"}
_WORD_LABELS = {"target word count", "target words", "word count", "words"}
_TOTAL_LABELS = {
    "total word count",
    "total words",
    "estimated total words",
    "estimated_total_words",
    "total estimated words",
}


def _looks_like_json(text: str) -> bool:
    """True when the model clearly intended a JSON object.

    Keyed on the opening brace alone: truncated JSON must be reported as a
    JSON failure, not silently reinterpreted as Markdown.
    """
    return text.lstrip().startswith("{")


def normalize_outline(raw_output: str) -> OutlineSchema:
    """Convert raw outline output into :class:`OutlineSchema`.

    Accepts either a JSON object or one of the Markdown forms observed from
    Ollama-class models:

    .. code-block:: markdown

        **Title:** ...

        **Section 1: ...**
        * Goal: ...
        * Target Word Count: 150 words

    and

    .. code-block:: markdown

        ### Section 1 – ...
        **Goal:** ...
        **Target Word Count:** 120–180

    The function is deterministic and total: any input either yields a valid
    ``OutlineSchema`` or raises :class:`NormalizationError`. It never guesses a
    missing or renamed field.
    """
    text = _strip_fences(raw_output)

    if not text.strip():
        raise NormalizationError(
            workflow="blog_generation",
            stage="outline",
            agent="outline_agent",
            output_format="empty",
            reason="model produced no output",
        )

    if _looks_like_json(text):
        payload = _parse_outline_json(text)
        output_format = "json"
    else:
        payload = _parse_outline_markdown(text)
        output_format = "markdown"

    return _validate(
        OutlineSchema,
        payload,
        stage="outline",
        agent="outline_agent",
        output_format=output_format,
    )


def _parse_outline_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NormalizationError(
            workflow="blog_generation",
            stage="outline",
            agent="outline_agent",
            output_format="json",
            reason=f"invalid JSON: {exc.msg}",
        ) from exc

    if not isinstance(payload, dict):
        raise NormalizationError(
            workflow="blog_generation",
            stage="outline",
            agent="outline_agent",
            output_format="json",
            reason=f"expected a JSON object, got {type(payload).__name__}",
        )
    return payload


def _heading_level(line: str) -> int:
    """Number of leading ``#`` markers on a Markdown heading line."""
    return len(line) - len(line.lstrip("#"))


def _clean_label(raw: str) -> str:
    """Reduce a bolded heading to its bare text."""
    return raw.strip().strip("*_`").strip()


def _is_section_heading(text: str) -> bool:
    """True when a line introduces a new outline section."""
    if _SECTION_PREFIX.match(text):
        return True
    lowered = text.lower()
    return lowered.startswith("section ") or lowered.startswith("part ")


def _parse_outline_markdown(text: str) -> dict[str, Any]:
    """Parse the Markdown outline forms into an ``OutlineSchema`` payload."""
    state: dict[str, Any] = {"title": None, "sections": []}
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = _HEADING.match(line)
        if heading:
            current = _consume_heading(
                _clean_label(heading.group("text")), state, level=_heading_level(line)
            )
            continue

        inline_bold = _BOLD_INLINE.match(line)
        if inline_bold:
            label = inline_bold.group("label").strip().lower()
            value = inline_bold.group("value").strip()
            if label in _TITLE_LABELS:
                state["title"] = value
            elif label in _GOAL_LABELS:
                if current is not None:
                    current["goal"] = value
            elif label in _WORD_LABELS:
                if current is not None:
                    current["target_words"] = _target_words(value)
            continue

        bullet = _BULLET.match(line)
        labelled = _LABELLED.match(line)
        matched: tuple[str, str] | None = None

        if bullet and labelled:
            matched = (labelled.group("label").strip().lower(), labelled.group("value").strip())
            label, value = matched
            if label in _GOAL_LABELS:
                if current is not None:
                    current["goal"] = value
                continue
            if label in _WORD_LABELS:
                if current is not None:
                    current["target_words"] = _target_words(value)
                continue

        if bullet:
            body = _clean_label(bullet.group("text"))
            if _is_section_heading(body):
                current = _consume_heading(body, state)
                continue
            # A bare bullet directly under a heading is the section's goal.
            if current is not None and "goal" not in current:
                current["goal"] = body
            continue

        if labelled:
            label, value = (
                matched
                if matched
                else (
                    labelled.group("label").strip().lower(),
                    labelled.group("value").strip(),
                )
            )
            if label in _TITLE_LABELS and current is None and state["title"] is None:
                state["title"] = value
            continue

        bold = _BOLD_LINE.match(line)
        if bold:
            body = _clean_label(bold.group("text"))
            if _is_section_heading(body):
                current = _consume_heading(body, state)
                continue

    sections: list[dict[str, Any]] = state["sections"]
    payload: dict[str, Any] = {"sections": sections}

    total = _find_total(text)
    if total is not None:
        payload["estimated_total_words"] = total
    elif sections:
        payload["estimated_total_words"] = sum(
            int(section["target_words"])
            for section in sections
            if isinstance(section.get("target_words"), int)
        )

    # Left absent when unknown so the schema error names the field rather than
    # the value silently becoming zero.
    title = state["title"]
    if title is None:
        raise NormalizationError(
            workflow="blog_generation",
            stage="outline",
            agent="outline_agent",
            output_format="markdown",
            reason="no title found",
            field_paths=["title"],
        )
    payload["title"] = title

    for index, section in enumerate(sections, start=1):
        missing = [
            name for name in ("id", "heading", "goal", "target_words") if name not in section
        ]
        if missing:
            raise NormalizationError(
                workflow="blog_generation",
                stage="outline",
                agent="outline_agent",
                output_format="markdown",
                reason=f"section {index} is incomplete",
                field_paths=[f"sections.{index - 1}.{name}" for name in missing],
            )

    return payload


def _consume_heading(
    body: str,
    state: dict[str, Any],
    *,
    level: int = 1,
) -> dict[str, Any] | None:
    """Record a heading line as either the title or a new section.

    A heading is read as a section when it names one ("Section 2 – …"), or when
    it is not the document's opening heading. The opening top-level heading is
    read as the title, which is what the observed Markdown form produces: ``#``
    for the title and ``###`` for each section.

    Returns the section the heading opened, or ``None`` when the line turned
    out to be the outline title.
    """
    sections: list[dict[str, Any]] = state["sections"]

    match = _SECTION_PREFIX.match(body)
    if match:
        section = {
            "id": f"section_{match.group('number')}",
            "heading": _SECTION_PREFIX.sub("", body).strip(),
        }
        sections.append(section)
        return section

    lowered = body.lower()
    if "title" in lowered and lowered.startswith(("title", "blog title")):
        state["title"] = (
            body.split(":", 1)[1].strip()
            if ":" in body
            else re.sub(r"^blog\s+title\s*", "", body, flags=re.IGNORECASE)
            .removeprefix("Title ")
            .strip()
        )
        return None

    if level <= 1 and not sections and state["title"] is None:
        state["title"] = body
        return None

    if _is_section_heading(body) or not sections:
        number = len(sections) + 1
        heading = (
            re.sub(r"^(section|part)\s*\d*\s*[.:)\-–—]?\s*", "", body, flags=re.IGNORECASE).strip()
            or body
        )
        section = {"id": f"section_{number}", "heading": heading}
        sections.append(section)
        return section

    return sections[-1]


def _target_words(value: str) -> int | None:
    """Read a word count written as ``150 words`` or a ``120–180`` range.

    A range takes its lower bound: the schema constrains a single number, and
    silently picking an arbitrary end of the range would be a guess.
    """
    range_match = _RANGE.search(value)
    if range_match:
        return _as_int(range_match.group(1))
    return _as_int(value)


def _find_total(text: str) -> int | None:
    """Find an explicit total-word figure, if the model stated one."""
    for line in text.splitlines():
        match = _LABELLED.match(line.strip())
        if match and match.group("label").strip().lower() in _TOTAL_LABELS:
            return _as_int(match.group("value"))
    return None
