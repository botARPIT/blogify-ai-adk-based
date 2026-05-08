"""AuthService — user registration, login, and JWT issuance."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import bcrypt
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.budget_config import INITIAL_BUDGET_TOKENS, INITIAL_BUDGET_USD
from src.models.orm_models import AuthUser, BudgetEntryType
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.services.local_auth_service import LocalAuthService


class AuthService:
    INITIAL_BUDGET_USD = Decimal("5.00")
    INITIAL_BUDGET_TOKENS = 500_000
    _local_auth = LocalAuthService()

    def __init__(
        self,
        user_repo: AuthUserRepository,
        budget_repo: BudgetRepository,
    ) -> None:
        self._user_repo = user_repo
        self._budget_repo = budget_repo

    async def register(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> AuthUser:
        existing = await self._user_repo.get_by_email(email)
        if existing:
            raise ValueError("Email already registered")

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        user = AuthUser(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        self._user_repo.session.add(user)
        await self._user_repo.session.flush()

        await self._budget_repo.write_entry(
            user_id=user.id,
            blog_session_id=None,
            agent_run_id=None,
            entry_type=BudgetEntryType.GRANT,
            tokens=self.INITIAL_BUDGET_TOKENS,
            amount_usd=self.INITIAL_BUDGET_USD,
            note="Initial budget on registration",
        )

        return user

    async def login(self, email: str, password: str) -> str:
        user = await self._user_repo.get_by_email(email)
        if not user:
            raise ValueError("Invalid credentials")

        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise ValueError("Invalid credentials")

        user.last_login_at = datetime.now(timezone.utc)
        await self._user_repo.session.flush()

        token = jwt.encode(
            {
                "sub": str(user.id),
                "exp": datetime.now(timezone.utc).timestamp() + 86400,
                "aud": self._local_auth.audience,
                "iss": self._local_auth.issuer,
            },
            self._local_auth.secret,
            algorithm="HS256",
        )
        return token

    async def get_current_user(self, user_id: int) -> AuthUser:
        user = await self._user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")
        return user