"""FastAPI dependency factories for application services."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.core.redis_pool import get_redis_client
from src.core.task_queue import task_queue
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.session_reservation_repository import SessionReservationRepository
from src.services.auth_service import AuthService
from src.services.blog_read_service import BlogReadService
from src.services.blog_service import BlogService
from src.services.budget_service import BudgetService
from src.services.tone_catalog_service import ToneCatalogService


def get_blog_service(session: AsyncSession = Depends(get_db_session)) -> BlogService:
    """Build the command-side blog service for this request transaction."""
    sessions = BlogSessionRepository(session)
    budget = BudgetService(
        BudgetRepository(session),
        sessions,
        BudgetAccountRepository(session),
        SessionReservationRepository(session),
    )
    return BlogService(
        sessions,
        BlogVersionRepository(session),
        budget,
        task_queue,
        get_redis_client(),
    )


def get_blog_read_service(
    session: AsyncSession = Depends(get_db_session),
) -> BlogReadService:
    return BlogReadService(session)


def get_tone_catalog_service(
    session: AsyncSession = Depends(get_db_session),
) -> ToneCatalogService:
    return ToneCatalogService(session, get_redis_client())


def get_auth_service(session: AsyncSession = Depends(get_db_session)) -> AuthService:
    return AuthService(
        AuthUserRepository(session),
        BudgetRepository(session),
        BudgetAccountRepository(session),
    )
