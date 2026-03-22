"""Webhook emitter for Blogify service mode callbacks."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from src.models.schemas import WebhookEventEnvelope

logger = logging.getLogger(__name__)


class WebhookEmitter:
    """Async webhook event emitter for Blogify server callbacks.

    Emits typed events when blog session state changes:
        blog.session.queued
        blog.session.processing
        blog.review.required
        blog.version.created
        blog.session.completed
        blog.session.failed
        blog.session.budget_exhausted
    """

    def __init__(self, callback_url: Optional[str], timeout: float = 5.0) -> None:
        self._callback_url = callback_url
        self._timeout = timeout

    async def emit(self, event: WebhookEventEnvelope) -> bool:
        """Fire-and-forget webhook call. Returns True if delivery succeeded."""
        if not self._callback_url:
            logger.debug("No callback URL configured — skipping webhook emit")
            return False

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._callback_url,
                    json=event.model_dump(mode="json"),
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code >= 400:
                    logger.warning(
                        "Webhook delivery failed",
                        extra={
                            "event_type": event.event_type,
                            "status_code": response.status_code,
                            "session_id": event.session_id,
                        },
                    )
                    return False
                return True
        except Exception as exc:
            logger.error(
                "Webhook emit error",
                extra={"event_type": event.event_type, "error": str(exc)},
                exc_info=True,
            )
            return False

    async def emit_queued(self, session_id: int, tenant_id: int, end_user_id: int) -> None:
        await self.emit(WebhookEventEnvelope(
            event_type="blog.session.queued",
            session_id=session_id,
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            status="queued",
            current_stage=None,
            current_version_number=None,
            budget_spent_usd=0.0,
            budget_spent_tokens=0,
            remaining_revision_iterations=0,
            requires_human_review=False,
            occurred_at=datetime.utcnow(),
        ))

    async def emit_review_required(
        self,
        session_id: int,
        tenant_id: int,
        end_user_id: int,
        version_number: int,
        remaining_iterations: int,
        budget_spent_usd: float,
        budget_spent_tokens: int,
    ) -> None:
        await self.emit(WebhookEventEnvelope(
            event_type="blog.review.required",
            session_id=session_id,
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            status="awaiting_human_review",
            current_stage="editor",
            current_version_number=version_number,
            budget_spent_usd=budget_spent_usd,
            budget_spent_tokens=budget_spent_tokens,
            remaining_revision_iterations=remaining_iterations,
            requires_human_review=True,
            occurred_at=datetime.utcnow(),
        ))

    async def emit_completed(
        self,
        session_id: int,
        tenant_id: int,
        end_user_id: int,
        version_number: int,
        budget_spent_usd: float,
        budget_spent_tokens: int,
    ) -> None:
        await self.emit(WebhookEventEnvelope(
            event_type="blog.session.completed",
            session_id=session_id,
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            status="completed",
            current_stage=None,
            current_version_number=version_number,
            budget_spent_usd=budget_spent_usd,
            budget_spent_tokens=budget_spent_tokens,
            remaining_revision_iterations=0,
            requires_human_review=False,
            occurred_at=datetime.utcnow(),
        ))

    async def emit_failed(
        self,
        session_id: int,
        tenant_id: int,
        end_user_id: int,
        reason: str,
        budget_spent_usd: float = 0.0,
        budget_spent_tokens: int = 0,
    ) -> None:
        await self.emit(WebhookEventEnvelope(
            event_type="blog.session.failed",
            session_id=session_id,
            tenant_id=tenant_id,
            end_user_id=end_user_id,
            status="failed",
            current_stage=None,
            current_version_number=None,
            budget_spent_usd=budget_spent_usd,
            budget_spent_tokens=budget_spent_tokens,
            remaining_revision_iterations=0,
            requires_human_review=False,
            payload={"reason": reason},
            occurred_at=datetime.utcnow(),
        ))
