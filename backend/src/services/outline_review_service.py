"""Outline review gate for canonical blog sessions."""

from __future__ import annotations

from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.schemas import OutlineReviewDecision, OutlineReviewRequest, OutlineSchema


class OutlineReviewService:
    """Manage human review of the generated outline before full drafting."""

    def __init__(
        self,
        session_repo: BlogSessionRepository,
    ) -> None:
        self._session_repo = session_repo

    async def process_review(
        self,
        blog_session_id: int,
        request: OutlineReviewRequest,
    ) -> OutlineReviewDecision:
        session = await self._session_repo.get_by_id(blog_session_id)
        if session is None:
            raise ValueError(f"Blog session {blog_session_id} not found")
        if not session.outline_data:
            raise ValueError(f"Blog session {blog_session_id} has no generated outline")

        outline_data = (
            request.edited_outline.model_dump()
            if request.edited_outline is not None
            else session.outline_data
        )

        await self._session_repo.update_outline(
            blog_session_id,
            outline_data=outline_data,
            outline_feedback=request.feedback_text,
        )
        if request.action == "approve":
            await self._session_repo.update_status(
                blog_session_id,
                BlogSessionStatus.QUEUED,
                current_stage="outline_approved",
            )
            return OutlineReviewDecision(
                session_id=blog_session_id,
                action=request.action,
                new_status=BlogSessionStatus.QUEUED.value,
                current_stage="outline_approved",
                requires_human_review=False,
                outline=request.edited_outline or OutlineSchema.model_validate(outline_data),
                message="Outline approved. Final drafting has been queued.",
            )

        await self._session_repo.update_status(
            blog_session_id,
            BlogSessionStatus.AWAITING_OUTLINE_REVIEW,
            current_stage="outline_review",
        )
        return OutlineReviewDecision(
            session_id=blog_session_id,
            action=request.action,
            new_status=BlogSessionStatus.AWAITING_OUTLINE_REVIEW.value,
            current_stage="outline_review",
            requires_human_review=True,
            outline=request.edited_outline or OutlineSchema.model_validate(outline_data),
            message="Outline changes saved. Review again or approve to continue.",
        )
