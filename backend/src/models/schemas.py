"""Pydantic schemas for agent I/O and canonical API contracts.

Includes:
- Legacy agent schemas (IntentSchema, OutlineSchema, etc.) — unchanged
- Phase 1 new domain types for the canonical request/response contract
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent I/O schemas (legacy — unchanged)
# ---------------------------------------------------------------------------


class IntentSchema(BaseModel):
    """Intent classification result."""

    status: str = Field(description="CLEAR | UNCLEAR_TOPIC | MULTI_TOPIC | MISSING_AUDIENCE")
    message: str = Field(description="Message explaining the classification")


class SectionSchema(BaseModel):
    """Blog section definition."""

    id: str = Field(description="Unique section identifier")
    heading: str = Field(description="Section heading")
    goal: str = Field(description="What this section should accomplish")
    target_words: int = Field(ge=80, le=300, description="Target word count")


class OutlineSchema(BaseModel):
    """Blog outline structure."""

    title: str = Field(max_length=120, description="Blog title")
    sections: list[SectionSchema] = Field(
        min_length=3, max_length=7, description="Blog sections"
    )
    estimated_total_words: int = Field(ge=300, le=2000, description="Total estimated words")


class ResearchSourceSchema(BaseModel):
    """Research source from Tavily."""

    title: str
    url: str
    content: str
    score: float = Field(ge=0.0, le=1.0)


class ResearchDataSchema(BaseModel):
    """Structured research data."""

    topic: str
    summary: str
    sources: list[ResearchSourceSchema]
    total_sources: int


class EditorReviewSchema(BaseModel):
    """Editor review result with approval decision."""

    approved: bool = Field(description="Whether blog is approved for publication")
    feedback: str = Field(description="Specific issues if not approved, empty if approved")
    final_blog: str = Field(description="Polished blog content if approved")
    sources_section: str = Field(description="Formatted sources/references section")


class FinalBlogSchema(BaseModel):
    """Final blog output."""

    title: str = Field(description="Final blog title")
    content: str = Field(description="Complete blog content with sources")
    word_count: int = Field(ge=300, description="Actual word count")
    sources_count: int = Field(ge=0, description="Number of sources cited")


# ---------------------------------------------------------------------------
# Phase 1 — New canonical domain types
# ---------------------------------------------------------------------------


class ResolvedIdentity(BaseModel):
    """Resolved caller identity from API key + request body."""

    service_client_id: int
    tenant_id: int
    end_user_id: int
    mode: str  # standalone | blogify_service
    external_user_id: str
    external_tenant_id: Optional[str] = None


class BudgetDecision(BaseModel):
    """Result of a budget preflight check or reserve operation."""

    allowed: bool
    reason: Optional[str] = None
    reserved_usd: float = 0.0
    reserved_tokens: int = 0
    daily_remaining_usd: float = 0.0
    daily_remaining_tokens: int = 0
    session_remaining_usd: float = 0.0
    session_remaining_tokens: int = 0


class BudgetSnapshot(BaseModel):
    """Point-in-time budget snapshot for an end user."""

    end_user_id: int
    tenant_id: int
    daily_spent_usd: float
    daily_spent_tokens: int
    daily_limit_usd: float
    daily_limit_tokens: int
    active_sessions: int
    max_concurrent_sessions: int
    remaining_revision_iterations: int


class BlogSessionState(BaseModel):
    """External representation of a blog session."""

    session_id: int
    status: str
    current_stage: Optional[str]
    iteration_count: int
    topic: str
    audience: Optional[str]
    requires_human_review: bool
    budget_spent_usd: float
    budget_spent_tokens: int
    remaining_revision_iterations: int
    current_version_number: Optional[int]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class BlogVersionView(BaseModel):
    """External representation of a blog version."""

    version_id: int
    session_id: int
    version_number: int
    source_type: str
    title: Optional[str]
    content_markdown: Optional[str]
    word_count: int
    sources_count: int
    editor_status: str
    created_by: str
    created_at: datetime


class HumanReviewRequest(BaseModel):
    """Request body for the /review endpoint."""

    action: str = Field(
        description="approve | request_revision | reject",
        pattern="^(approve|request_revision|reject)$",
    )
    feedback_text: Optional[str] = Field(
        default=None,
        description="Required when action=request_revision",
    )
    reviewer_user_id: str = Field(description="ID of the user submitting the review")


class HumanReviewDecision(BaseModel):
    """Response after a human review action."""

    session_id: int
    version_id: int
    action: str
    new_status: str
    iteration_count: int
    requires_human_review: bool
    message: str


class RevisionRequest(BaseModel):
    """Internal payload for a revision loop."""

    session_id: int
    version_id: int
    editor_feedback: str
    human_feedback: str
    iteration_number: int


class AgentRunSummary(BaseModel):
    """Lightweight summary of an agent run for API responses."""

    run_id: int
    stage_name: str
    agent_name: str
    status: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]


class WebhookEventEnvelope(BaseModel):
    """Typed wrapper for Blogify callback events."""

    event_type: str = Field(
        description=(
            "blog.session.queued | blog.session.processing | blog.review.required | "
            "blog.version.created | blog.session.completed | blog.session.failed | "
            "blog.session.budget_exhausted"
        )
    )
    session_id: int
    tenant_id: int
    end_user_id: int
    status: str
    current_stage: Optional[str]
    current_version_number: Optional[int]
    budget_spent_usd: float
    budget_spent_tokens: int
    remaining_revision_iterations: int
    requires_human_review: bool
    payload: Optional[dict[str, Any]] = None
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
