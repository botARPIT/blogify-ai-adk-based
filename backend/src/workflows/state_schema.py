"""Session state keys, in one place.

Two layers need to agree on the shape of a blog session's state: the pipeline,
which seeds a new session, and the executor, which writes a snapshot back to
Postgres. When both enumerate the keys separately they can drift, and such a
drift is silent -- a key stored but never seeded, or seeded but never persisted.

This module is the single definition. Adding a key here makes both sides
obligation-bound: :func:`empty_session_state` seeds it and
:func:`build_session_state` produces it, so a new field cannot be added to one
side alone.
"""

from __future__ import annotations

from typing import Any, Final

from src.core.workflow_state_keys import RESEARCH_TOOL_DATA_KEY

TOPIC_KEY: Final = "topic"
AUDIENCE_KEY: Final = "audience"
TONE_KEY: Final = "tone"
INTENT_RESULT_KEY: Final = "intent_result"
OUTLINE_KEY: Final = "blog_outline"
APPROVED_OUTLINE_KEY: Final = "approved_outline"
OUTLINE_FEEDBACK_KEY: Final = "outline_feedback"
OUTLINE_REVIEW_RESULT_KEY: Final = "outline_review_result"
RESEARCH_DATA_KEY: Final = "research_data"
BLOG_DRAFT_KEY: Final = "blog_draft"
EDITOR_REVIEW_KEY: Final = "editor_review"

#: Every key that makes up a blog session's state.
#:
#: ``refinement_iterations`` is deliberately absent: it counts iterations within
#: a single invocation, and carrying a stale count into the next invocation would
#: mis-bound its writer/editor cycle.
SESSION_STATE_KEYS: Final[tuple[str, ...]] = (
    TOPIC_KEY,
    AUDIENCE_KEY,
    TONE_KEY,
    INTENT_RESULT_KEY,
    OUTLINE_KEY,
    APPROVED_OUTLINE_KEY,
    OUTLINE_FEEDBACK_KEY,
    OUTLINE_REVIEW_RESULT_KEY,
    RESEARCH_DATA_KEY,
    BLOG_DRAFT_KEY,
    EDITOR_REVIEW_KEY,
)

#: Counts writer/editor cycles within one invocation. Workflow-only, never
#: persisted.
REFINEMENT_ITERATIONS_KEY: Final = "refinement_iterations"

#: Empty seed per key. The value type must match what each consumer expects:
#: agents interpolate these straight into prompts, so a wrong default type
#: surfaces as a rendering error deep inside a model call rather than here.
_EMPTY_BY_KEY: Final[dict[str, Any]] = {
    TOPIC_KEY: "",
    AUDIENCE_KEY: "",
    TONE_KEY: "",
    INTENT_RESULT_KEY: {},
    OUTLINE_KEY: {},
    APPROVED_OUTLINE_KEY: {},
    OUTLINE_FEEDBACK_KEY: "",
    OUTLINE_REVIEW_RESULT_KEY: {},
    RESEARCH_DATA_KEY: {},
    BLOG_DRAFT_KEY: "",
    EDITOR_REVIEW_KEY: {},
}


def empty_session_state(topic: str = "", audience: str = "", tone: str = "") -> dict[str, Any]:
    """Seed every session key with its empty value."""
    state: dict[str, Any] = {key: _fresh(value) for key, value in _EMPTY_BY_KEY.items()}
    state[TOPIC_KEY] = topic
    state[AUDIENCE_KEY] = audience
    state[TONE_KEY] = tone
    return state


def build_session_state(
    *,
    topic: str,
    audience: str,
    tone: str = "",
    intent_result: dict[str, Any] | None = None,
    blog_outline: dict[str, Any] | None = None,
    approved_outline: dict[str, Any] | None = None,
    outline_feedback: str = "",
    outline_review_result: dict[str, Any] | None = None,
    research_data: dict[str, Any] | None = None,
    blog_draft: str = "",
    editor_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete session snapshot from pipeline output.

    The result always carries every key in :data:`SESSION_STATE_KEYS`, so a
    snapshot written to Postgres can never be partially populated. The keyword
    signature is the guard against unknown fields: an unrecognised key raises
    ``TypeError`` rather than being stored silently.
    """
    return {
        TOPIC_KEY: topic,
        AUDIENCE_KEY: audience,
        TONE_KEY: tone,
        INTENT_RESULT_KEY: intent_result or {},
        OUTLINE_KEY: blog_outline or {},
        APPROVED_OUTLINE_KEY: approved_outline or {},
        OUTLINE_FEEDBACK_KEY: outline_feedback or "",
        OUTLINE_REVIEW_RESULT_KEY: outline_review_result or {},
        RESEARCH_DATA_KEY: research_data or {},
        BLOG_DRAFT_KEY: blog_draft or "",
        EDITOR_REVIEW_KEY: editor_review or {},
    }


def missing_session_state_keys(state: dict[str, Any]) -> set[str]:
    """Session keys absent from ``state``; empty when the snapshot is complete."""
    return set(SESSION_STATE_KEYS) - set(state)


def _fresh(value: Any) -> Any:
    """Copy mutable defaults so two sessions never share one dict."""
    return dict(value) if isinstance(value, dict) else value


__all__ = [
    "APPROVED_OUTLINE_KEY",
    "AUDIENCE_KEY",
    "BLOG_DRAFT_KEY",
    "EDITOR_REVIEW_KEY",
    "INTENT_RESULT_KEY",
    "OUTLINE_FEEDBACK_KEY",
    "OUTLINE_KEY",
    "OUTLINE_REVIEW_RESULT_KEY",
    "REFINEMENT_ITERATIONS_KEY",
    "RESEARCH_DATA_KEY",
    "RESEARCH_TOOL_DATA_KEY",
    "SESSION_STATE_KEYS",
    "TONE_KEY",
    "TOPIC_KEY",
    "build_session_state",
    "empty_session_state",
    "missing_session_state_keys",
]
