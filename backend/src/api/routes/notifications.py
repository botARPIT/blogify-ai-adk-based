"""In-app notification routes for authenticated users."""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.api.auth import ensure_csrf_header, require_authenticated_user
from src.models.repository import db_repository
from src.models.repositories.notification_repository import NotificationRepository
from src.models.schemas import (
    MarkNotificationReadResponse,
    NotificationListResponse,
    NotificationView,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


def _to_view(notification) -> NotificationView:
    return NotificationView(
        id=int(notification.id),
        type=notification.type,
        title=notification.title,
        message=notification.message,
        session_id=int(notification.session_id) if notification.session_id is not None else None,
        status="read" if notification.is_read else "unread",
        created_at=notification.created_at,
        action_url=notification.action_url,
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    request: Request,
    limit: int = 20,
    unread_only: bool = False,
):
    user = require_authenticated_user(request)
    async with db_repository.async_session() as session:
        repo = NotificationRepository(session)
        items = await repo.list_for_user(
            user_id=int(user.user_id),
            limit=min(max(limit, 1), 100),
            unread_only=unread_only,
        )
        return NotificationListResponse(items=[_to_view(item) for item in items])


@router.post("/{notification_id}/read", response_model=MarkNotificationReadResponse)
async def mark_notification_read(notification_id: int, request: Request):
    ensure_csrf_header(request)
    user = require_authenticated_user(request)
    async with db_repository.async_session() as session:
        async with session.begin():
            repo = NotificationRepository(session)
            updated = await repo.mark_read(notification_id, int(user.user_id))
            return MarkNotificationReadResponse(ok=updated, updated=1 if updated else 0)


@router.post("/read-all", response_model=MarkNotificationReadResponse)
async def mark_all_notifications_read(request: Request):
    ensure_csrf_header(request)
    user = require_authenticated_user(request)
    async with db_repository.async_session() as session:
        async with session.begin():
            repo = NotificationRepository(session)
            updated = await repo.mark_all_read(int(user.user_id))
            return MarkNotificationReadResponse(ok=True, updated=updated)
