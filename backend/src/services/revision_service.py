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
    EndUser,
    HumanReviewAction,
)
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.human_review_repository import HumanReviewRepository
from src.models.repositories.notification_repository import NotificationRepository
from src.models.schemas import HumanReviewDecision, HumanReviewRequest
from src.services.notification_service import NotificationService

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
        auth_user_repo: AuthUserRepository | None = None,
        notification_repo: NotificationRepository | None = None,
    ) -> None:
        self._session_repo = session_repo
        self._version_repo = version_repo
        self._review_repo = review_repo
        self._budget_repo = budget_repo
        self._auth_user_repo = auth_user_repo
        self._notification_repo = notification_repo

    async def _emit_notification(
        self,
        *,
        session,
        type: str,
        title: str,
        message: str,
        action_url: str,
    ) -> None:
        if self._auth_user_repo is None or self._notification_repo is None:
            return
            
        end_user = await self._session_repo._session.get(EndUser, session.end_user_id)
        if end_user is None:
            return

        notification_service = NotificationService(
            auth_user_repo=self._auth_user_repo,
            notification_repo=self._notification_repo,
        )
        await notification_service.create_for_end_user(
            end_user=end_user,
            type=type,
            title=title,
            message=message,
            session_id=session.id,
            action_url=action_url,
        )

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
            await self._emit_notification(
                session=session,
                type="blog_completed",
                title="Blog completed",
                message=f"Session {blog_session_id} has been approved and is ready to read.",
                action_url=f"/sessions/{blog_session_id}/output",
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
            await self._emit_notification(
                session=session,
                type="blog_failed",
                title="Blog rejected",
                message=f"Session {blog_session_id} was rejected during final review.",
                action_url=f"/sessions/{blog_session_id}/progress",
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
                await self._session_repo.update_status(
                    blog_session_id,
                    BlogSessionStatus.FAILED,
                    current_stage="revision_limit_reached",
                )
                logger.warning(
                    "Revision limit reached for session %d. Rejecting further revisions.",
                    blog_session_id,
                )
                await self._emit_notification(
                    session=session,
                    type="blog_failed",
                    title="Revision limit reached",
                    message=f"Session {blog_session_id} can no longer continue because the revision limit was reached.",
                    action_url=f"/sessions/{blog_session_id}/progress",
                )
                return HumanReviewDecision(
                    session_id=blog_session_id,
                    version_id=blog_version_id,
                    action=action.value,
                    new_status=BlogSessionStatus.FAILED.value,
                    iteration_count=session.iteration_count,
                    requires_human_review=False,
                    message=(
                        f"Revision limit ({policy_max_iterations}) reached. "
                        "No further revisions allowed for this session."
                    ),
                )

            # Create the next draft version so the review loop has a concrete
            # resume point even before automated revision generation is wired.
            next_version = await self._version_repo.create(
                blog_session_id=blog_session_id,
                source_type=BlogVersionSource.HUMAN_REVISION,
                content_markdown=version.content_markdown,
                title=version.title,
                word_count=version.word_count,
                sources_count=version.sources_count,
                editor_status=BlogEditorStatus.DRAFT,
                created_by=BlogCreatedBy.HUMAN,
            )

            new_count = await self._session_repo.increment_iteration(blog_session_id)
            await self._session_repo.update_status(
                blog_session_id,
                BlogSessionStatus.REVISION_REQUESTED,
                current_stage="revision_requested",
            )

            return HumanReviewDecision(
                session_id=blog_session_id,
                version_id=next_version.id,
                action=action.value,
                new_status=BlogSessionStatus.REVISION_REQUESTED.value,
                iteration_count=new_count,
                requires_human_review=False,
                message=(
                    f"Revision #{new_count} requested. "
                    f"Draft version {next_version.version_number} created with reviewer feedback. "
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
        await self._emit_notification(
            session=await self._session_repo.get_by_id(blog_session_id),
            type="final_review_required",
            title="Draft ready for final review",
            message=f"Session {blog_session_id} is ready for human approval.",
            action_url=f"/sessions/{blog_session_id}/final-review",
        )
        return version.id
