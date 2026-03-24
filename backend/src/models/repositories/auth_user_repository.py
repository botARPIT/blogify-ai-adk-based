"""Repository for local auth users."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import AuthUser


class AuthUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> Optional[AuthUser]:
        result = await self._session.execute(
            select(AuthUser).where(func.lower(AuthUser.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[AuthUser]:
        result = await self._session.execute(select(AuthUser).where(AuthUser.id == user_id))
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(AuthUser))
        return int(result.scalar_one())

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str | None = None,
    ) -> AuthUser:
        user = AuthUser(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=display_name,
            is_active=True,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def touch_last_login(self, user_id: int) -> None:
        user = await self.get_by_id(user_id)
        if user is not None:
            user.last_login_at = datetime.now(timezone.utc)
