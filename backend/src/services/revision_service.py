"""RevisionService — manages the HITL editor review and revision loops.

Phase 5: HITL at editor stage.

Workflow:
    1. Pipeline produces editor output → session enters awaiting_human_review
    2. User calls /review with action=approve|request_revision|reject
    3. If revision: enqueue revision_writer + revision_editor stages
    4. Repeat until approved, rejected, or revision limit reached
    5. Budget is charged per revision loop
"""

from __future__ import annotations

import logging
from typing import Optional

from src.models.orm_models import (
    BlogCreatedBy,
    BlogEditorStatus,
    BlogSessionStatus,
    BlogVersionSource,
    HumanReviewAction,
)
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.human_review_repository import HumanReviewRepository
from src.models.schemas import HumanReviewDecision, HumanReviewRequest

logger = logging.getLogger(__name__)


class RevisionLimitError(Exception):
    """Raised when the max revision iterations have been reached."""
    pass


class RevisionService:
    """Orchestrates HITL human review events and revision iteration logic."""

    def __init__(
        self,
        session_repo: BlogSessionRepository,
        version_repo: BlogVersionRepository,
        review_repo: HumanReviewRepository,
        budget_repo: BudgetRepository,
    ) -> None:
        self._session_repo = session_repo
        self._version_repo = version_repo
        self._review_repo = review_repo
        self._budget_repo = budget_repo

    async def process_review(
        self,
        blog_session_id: int,
        blog_version_id: int,
        request: HumanReviewRequest,
        policy_max_iterations: int = 3,
    ) -> HumanReviewDecision:
        """Process a human review action and return the new session state."""
        session = await self._session_repo.get_by_id(blog_session_id)
        if session is None:
            raise ValueError(f"Blog session {blog_session_id} not found")

        version = await self._version_repo.get_by_id(blog_version_id)
        if version is None:
            raise ValueError(f"Blog version {blog_version_id} not found")

        action = HumanReviewAction(request.action)

        # Record the human review event
        await self._review_repo.create(
            blog_session_id=blog_session_id,
            blog_version_id=blog_version_id,
            reviewer_user_id=request.reviewer_user_id,
            action=action,
            feedback_text=request.feedback_text,
        )

        if action == HumanReviewAction.APPROVE:
            await self._version_repo.mark_approved(blog_version_id)
            await self._session_repo.update_status(
                blog_session_id, BlogSessionStatus.COMPLETED
            )
            return HumanReviewDecision(
                session_id=blog_session_id,
                version_id=blog_version_id,
                action=action.value,
                new_status=BlogSessionStatus.COMPLETED.value,
                iteration_count=session.iteration_count,
                requires_human_review=False,
                message="Blog approved. Session completed.",
            )

        elif action == HumanReviewAction.REJECT:
            await self._version_repo.mark_rejected(blog_version_id)
            await self._session_repo.update_status(
                blog_session_id, BlogSessionStatus.FAILED
            )
            return HumanReviewDecision(
                session_id=blog_session_id,
                version_id=blog_version_id,
                action=action.value,
                new_status=BlogSessionStatus.FAILED.value,
                iteration_count=session.iteration_count,
                requires_human_review=False,
                message="Blog rejected. Session closed.",
            )

        elif action == HumanReviewAction.REQUEST_REVISION:
            # Check revision limit
            if session.iteration_count >= policy_max_iterations:
                # Exhausted — surface latest draft as completed
                await self._session_repo.update_status(
                    blog_session_id, BlogSessionStatus.COMPLETED
                )
                logger.warning(
                    "Revision limit reached for session %d. Completing with latest draft.",
                    blog_session_id,
                )
                return HumanReviewDecision(
                    session_id=blog_session_id,
                    version_id=blog_version_id,
                    action=action.value,
                    new_status=BlogSessionStatus.COMPLETED.value,
                    iteration_count=session.iteration_count,
                    requires_human_review=False,
                    message=(
                        f"Revision limit ({policy_max_iterations}) reached. "
                        "Completed with latest available draft."
                    ),
                )

            # Increment iteration and transition to revision_requested
            new_count = await self._session_repo.increment_iteration(blog_session_id)
            await self._session_repo.update_status(
                blog_session_id,
                BlogSessionStatus.REVISION_REQUESTED,
                current_stage="revision_writer",
            )

            return HumanReviewDecision(
                session_id=blog_session_id,
                version_id=blog_version_id,
                action=action.value,
                new_status=BlogSessionStatus.REVISION_REQUESTED.value,
                iteration_count=new_count,
                requires_human_review=True,
                message=(
                    f"Revision #{new_count} enqueued. "
                    f"{policy_max_iterations - new_count} iterations remaining."
                ),
            )

        raise ValueError(f"Unhandled review action: {action}")

    async def record_editor_output(
        self,
        blog_session_id: int,
        content_markdown: str,
        title: Optional[str] = None,
        word_count: int = 0,
        sources_count: int = 0,
        editor_approved: bool = False,
    ) -> int:
        """Persist editor output as a new blog version and transition session to review."""
        editor_status = (
            BlogEditorStatus.EDITOR_APPROVED if editor_approved else BlogEditorStatus.DRAFT
        )
        version = await self._version_repo.create(
            blog_session_id=blog_session_id,
            source_type=BlogVersionSource.INITIAL_GENERATION,
            content_markdown=content_markdown,
            title=title,
            word_count=word_count,
            sources_count=sources_count,
            editor_status=editor_status,
            created_by=BlogCreatedBy.SYSTEM,
        )
        await self._session_repo.update_status(
            blog_session_id,
            BlogSessionStatus.AWAITING_HUMAN_REVIEW,
            current_stage="awaiting_review",
        )
        return version.id
