"""Canonical blog generation and HITL review routes (Phase 4 + 5).

Covers both:
  - Standalone adapter routes (/api/v1/blogs/*)
  - Aliased from internal service adapter (/internal/ai/blogs/*)

Budget enforcement (Phase 3) and HITL review (Phase 5) integrated here.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.models.schemas import (
    BudgetSnapshot,
    HumanReviewDecision,
    HumanReviewRequest,
)

canonical_router = APIRouter(prefix="/api/v1", tags=["Blog Generation"])
internal_router = APIRouter(prefix="/internal/ai", tags=["Internal Service"])


# ---------------------------------------------------------------------------
# Request / Response models for the canonical routes
# ---------------------------------------------------------------------------


class GenerateBlogRequest(BaseModel):
    """Request body for blog generation (standalone mode)."""

    topic: str = Field(min_length=10, max_length=500, description="Blog topic")
    audience: Optional[str] = Field(default=None, max_length=255)
    tone: Optional[str] = Field(default=None, max_length=100)
    # Standalone mode: user_id comes from auth token; provided here for simplicity
    user_id: str = Field(description="Caller's user identifier")


class ServiceGenerateBlogRequest(BaseModel):
    """Request body for Blogify server-to-server blog generation."""

    topic: str = Field(min_length=10, max_length=500)
    audience: Optional[str] = Field(default=None)
    tone: Optional[str] = Field(default=None)

    # Identity fields required for service mode
    tenant_id: str = Field(description="Blogify workspace/org ID")
    end_user_id: str = Field(description="ID of the end user requesting the blog")
    request_id: str = Field(description="Idempotency key for this request")
    external_blog_id: Optional[str] = Field(default=None, description="Blogify blog record ID")
    callback_url: Optional[str] = Field(default=None, description="Webhook callback URL")


class GenerateBlogResponse(BaseModel):
    """Response after accepting a blog generation request."""

    session_id: str
    status: str
    message: str
    budget_reserved_usd: float = 0.0


class SessionStatusResponse(BaseModel):
    """Polling endpoint response — current session state."""

    session_id: str
    status: str
    current_stage: Optional[str]
    iteration_count: int
    topic: str
    requires_human_review: bool
    budget_spent_usd: float
    budget_spent_tokens: int
    current_version_number: Optional[int]


# ---------------------------------------------------------------------------
# Standalone routes
# ---------------------------------------------------------------------------


@canonical_router.post("/blogs/generate", response_model=GenerateBlogResponse)
async def generate_blog(request: GenerateBlogRequest):
    """Accept a new blog generation request (standalone mode).

    Phase 0: Returns a pending acknowledgement.
    Phase 3 will add budget preflight before enqueue.
    Phase 4 will wire full identity resolution.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Blog generation pipeline is being migrated to ADK-native orchestration. "
            "This endpoint is not yet wired to the canonical data model."
        ),
    )


@canonical_router.get("/blogs/{session_id}", response_model=SessionStatusResponse)
async def get_blog_session(session_id: str):
    """Poll session status."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Session status polling requires canonical data model migration.",
    )


@canonical_router.post(
    "/blogs/{session_id}/review",
    response_model=HumanReviewDecision,
    summary="Submit human review decision (approve / request_revision / reject)",
)
async def submit_human_review(
    session_id: str,
    version_id: int,
    request: HumanReviewRequest,
):
    """Phase 5: HITL review endpoint.

    After the editor stage completes, the session enters 'awaiting_human_review'.
    The reviewer calls this endpoint to approve, request revision, or reject the blog.

    Args:
        session_id: The blog session ID.
        version_id: The specific version being reviewed (latest version from polling).
        request: Review action and optional feedback.

    Returns:
        HumanReviewDecision: New session state after the review action.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="HITL review requires canonical data model migration.",
    )


@canonical_router.get("/budgets/me", response_model=BudgetSnapshot)
async def get_my_budget(user_id: str):
    """Return current budget snapshot for the calling user (standalone mode)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Budget snapshot requires canonical data model migration.",
    )


# ---------------------------------------------------------------------------
# Internal service routes (Blogify server-to-server)
# ---------------------------------------------------------------------------


@internal_router.post("/blogs", response_model=GenerateBlogResponse)
async def service_generate_blog(
    request: ServiceGenerateBlogRequest,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Accept blog generation request from Blogify backend (service mode).

    Requires:
        X-Internal-Api-Key: header with Blogify service API key
        tenant_id, end_user_id, request_id in body
    """
    if not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Api-Key header is required for service mode",
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Service-mode blog generation requires canonical data model migration.",
    )


@internal_router.get("/blogs/{session_id}", response_model=SessionStatusResponse)
async def service_get_session(session_id: str):
    """Get session status (service mode)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Service-mode session status requires canonical data model migration.",
    )


@internal_router.post("/blogs/{session_id}/review", response_model=HumanReviewDecision)
async def service_submit_review(
    session_id: str,
    version_id: int,
    request: HumanReviewRequest,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Submit review (service mode). Mirrors standalone /review endpoint."""
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Service-mode review requires canonical data model migration.",
    )


@internal_router.get("/budgets/{end_user_id}", response_model=BudgetSnapshot)
async def service_get_budget(
    end_user_id: str,
    x_internal_api_key: Annotated[Optional[str], Header()] = None,
):
    """Return budget snapshot for a specific end user (service mode)."""
    if not x_internal_api_key:
        raise HTTPException(status_code=401, detail="X-Internal-Api-Key required")

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Service-mode budget requires canonical data model migration.",
    )
