"""Persistent notification helpers for canonical workflow events."""

from __future__ import annotations

from src.models.orm_models import EndUser
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.notification_repository import NotificationRepository


class NotificationService:
    def __init__(
        self,
        *,
        auth_user_repo: AuthUserRepository,
        notification_repo: NotificationRepository,
    ) -> None:
        self._auth_user_repo = auth_user_repo
        self._notification_repo = notification_repo

    async def _resolve_local_user_id(self, end_user: EndUser | None) -> int | None:
        if end_user is None:
            return None
        try:
            return int(end_user.external_user_id)
        except (TypeError, ValueError):
            return None

    async def create_for_end_user(
        self,
        *,
        end_user: EndUser | None,
        type: str,
        title: str,
        message: str,
        session_id: int | None = None,
        action_url: str | None = None,
        payload_json: dict | None = None,
        dedupe_unread: bool = True,
    ) -> None:
        user_id = await self._resolve_local_user_id(end_user)
        if user_id is None:
            return
        auth_user = await self._auth_user_repo.get_by_id(user_id)
        if auth_user is None:
            return
        if dedupe_unread and session_id is not None:
            existing = await self._notification_repo.get_unread_for_session_and_type(
                user_id=user_id,
                session_id=session_id,
                type=type,
            )
            if existing is not None:
                return
        await self._notification_repo.create(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            session_id=session_id,
            action_url=action_url,
            payload_json=payload_json,
        )
