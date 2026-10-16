"""Opt-in end-to-end fixtures backed by disposable PostgreSQL and Redis."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _test_urls() -> tuple[str, str]:
    database_url = os.getenv("BLOGIFY_TEST_DATABASE_URL")
    redis_url = os.getenv("BLOGIFY_TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("set BLOGIFY_TEST_DATABASE_URL and BLOGIFY_TEST_REDIS_URL for E2E tests")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("BLOGIFY_TEST_DATABASE_URL must use postgresql+asyncpg://")
    return database_url, redis_url


@pytest_asyncio.fixture
async def e2e(monkeypatch):
    """Real API, PostgreSQL, and Redis; provider calls are scripted per test."""
    database_url, redis_url = _test_urls()
    from src.api.auth import LocalAuthService
    from src.core.task_queue import TaskQueue
    from src.models.orm_models import AuthUser, Base, BudgetAccount

    schema = f"blogify_e2e_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, pool_size=2, max_overflow=0)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = admin_engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
        raise

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    import redis.asyncio as redis_async

    redis = redis_async.from_url(redis_url, decode_responses=True)
    prefix = f"blogify:e2e:{uuid.uuid4().hex}"
    monkeypatch.setattr(TaskQueue, "QUEUE_KEY", f"{prefix}:tasks")
    monkeypatch.setattr(TaskQueue, "PROCESSING_KEY", f"{prefix}:processing")
    monkeypatch.setattr(TaskQueue, "NOTIFY_CHANNEL", f"{prefix}:notify")
    monkeypatch.setattr("src.core.task_queue.get_redis_client", lambda: _return(redis))
    monkeypatch.setattr("src.core.redis_pool.get_redis_client", lambda: _return(redis))
    monkeypatch.setattr("src.api.routes.blog_routes.get_redis_client", lambda: _return(redis))
    monkeypatch.setattr("src.core.database.AsyncSessionFactory", sessions)
    monkeypatch.setattr("src.workers.blog_worker.AsyncSessionFactory", sessions)
    monkeypatch.setattr("src.workers.reaper.AsyncSessionFactory", sessions)

    async with sessions.begin() as db:
        user = AuthUser(email=f"{uuid.uuid4().hex}@example.test", password_hash="test")
        db.add(user)
        await db.flush()
        db.add(BudgetAccount(
            user_id=user.id,
            balance_usd=100,
            reserved_usd=0,
            total_granted_usd=100,
            total_spent_usd=0,
        ))
        await db.flush()
        user_id, email = user.id, user.email

    token = LocalAuthService().issue_token(
        LocalAuthServiceUser(user_id=user_id, email=email, display_name="E2E")
    )
    from src.api.main import app

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        yield E2EContext(
            client=client, sessions=sessions, redis=redis, user_id=user_id,
            queue_key=f"{prefix}:tasks",
        )
    finally:
        await client.aclose()
        await redis.aclose()
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def _return(value):
    return value


from dataclasses import dataclass

from src.services.local_auth_service import LocalAuthUser as LocalAuthServiceUser


@dataclass
class E2EContext:
    client: httpx.AsyncClient
    sessions: async_sessionmaker
    redis: object
    user_id: int
    queue_key: str


@pytest.fixture(autouse=True)
def mock_redis():
    """Override the root test suite's automatic Redis mock for E2E tests."""
    yield None


@pytest.fixture(autouse=True)
def mock_session_factory():
    """Override the root test suite's automatic database mock for E2E tests."""
    yield None
