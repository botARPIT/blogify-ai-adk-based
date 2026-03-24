"""Repository for persistent in-app notifications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import UserNotification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        message: str,
        session_id: int | None = None,
        action_url: str | None = None,
        payload_json: dict | None = None,
    ) -> UserNotification:
        notification = UserNotification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            session_id=session_id,
            action_url=action_url,
            payload_json=payload_json,
            is_read=False,
        )
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def list_for_user(
        self,
        *,
        user_id: int,
        limit: int = 20,
        unread_only: bool = False,
    ) -> list[UserNotification]:
        stmt = (
            select(UserNotification)
            .where(UserNotification.user_id == user_id)
            .order_by(UserNotification.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(UserNotification.is_read.is_(False))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(self, notification_id: int, user_id: int) -> Optional[UserNotification]:
        result = await self._session.execute(
            select(UserNotification).where(
                UserNotification.id == notification_id,
                UserNotification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        notification = await self.get_for_user(notification_id, user_id)
        if notification is None:
            return False
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
        return True

    async def mark_all_read(self, user_id: int) -> int:
        notifications = await self.list_for_user(user_id=user_id, limit=500, unread_only=True)
        now = datetime.now(timezone.utc)
        for notification in notifications:
            notification.is_read = True
            notification.read_at = now
        return len(notifications)

    async def get_unread_for_session_and_type(
        self,
        *,
        user_id: int,
        session_id: int,
        type: str,
    ) -> Optional[UserNotification]:
        result = await self._session.execute(
            select(UserNotification).where(
                UserNotification.user_id == user_id,
                UserNotification.session_id == session_id,
                UserNotification.type == type,
                UserNotification.is_read.is_(False),
            )
        )
        return result.scalar_one_or_none()
