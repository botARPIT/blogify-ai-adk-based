"""PostgreSQL locking and atomic-write checks for workflow outbox semantics.

Set BLOGIFY_TEST_DATABASE_URL to a disposable PostgreSQL database to run these.
The suite creates and drops a unique schema; it never uses DATABASE_URL.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.integration]


def database_url() -> str | None:
    return os.getenv("BLOGIFY_TEST_DATABASE_URL")


async def isolated_schema():
    """Create isolated tables and return an async engine plus its schema name."""
    from src.models.orm_models import Base

    url = database_url()
    if not url:
        pytest.skip("set BLOGIFY_TEST_DATABASE_URL to a disposable PostgreSQL database")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("BLOGIFY_TEST_DATABASE_URL must use postgresql+asyncpg://")

    schema = f"blogify_test_{uuid.uuid4().hex}"
    admin = create_async_engine(url, pool_size=2, max_overflow=0)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = admin.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
        raise
    return admin, engine, schema


@pytest.mark.asyncio
async def test_session_and_outbox_intent_rollback_together():
    from src.models.orm_models import AuthUser, BlogSession, WorkflowOutboxEvent

    admin, engine, schema = await isolated_schema()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            async with db.begin():
                user = AuthUser(email="atomicity@example.test", password_hash="not-a-real-hash")
                db.add(user)
                await db.flush()
                blog = BlogSession(user_id=user.id, topic="transaction test", audience="test", tone="professional")
                db.add(blog)
                await db.flush()
                db.add(WorkflowOutboxEvent(
                    event_type="blog.continue_generation",
                    aggregate_id=blog.id,
                    payload={"session_id": blog.id},
                ))
                await db.flush()
                await db.rollback()

        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BlogSession)) == 0
            assert await db.scalar(select(func.count()).select_from(WorkflowOutboxEvent)) == 0
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
async def test_skip_locked_prevents_two_workers_claiming_same_event():
    from src.models.orm_models import WorkflowOutboxEvent
    from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository

    admin, engine, schema = await isolated_schema()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as db:
            row = WorkflowOutboxEvent(
                event_type="blog.continue_generation",
                aggregate_id=991,
                payload={"session_id": 991},
            )
            db.add(row)
            await db.flush()
            event_id = row.id

        first = sessions()
        second = sessions()
        try:
            await first.begin()
            claimed = await WorkflowOutboxRepository(first).claim_event(
                event_id, worker_id="worker-a", lease_seconds=60
            )
            assert claimed is not None

            await second.begin()
            competing_claim = await WorkflowOutboxRepository(second).claim_event(
                event_id, worker_id="worker-b", lease_seconds=60
            )
            assert competing_claim is None

            await second.commit()
            await first.commit()
        finally:
            await first.close()
            await second.close()

        async with sessions() as db:
            persisted = await db.get(WorkflowOutboxEvent, event_id)
            assert persisted is not None
            assert persisted.status == "PROCESSING"
            assert persisted.locked_by == "worker-a"
            assert persisted.attempts == 1
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
async def test_new_session_persists_the_same_phase_as_its_initial_job():
    from src.models.orm_models import AuthUser, BlogSessionStatus
    from src.models.repositories.blog_session_repository import BlogSessionRepository

    admin, engine, schema = await isolated_schema()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as db:
            user = AuthUser(email="phase-check@example.test", password_hash="not-a-real-hash")
            db.add(user)
            await db.flush()
            blog = await BlogSessionRepository(db).create(
                user_id=user.id,
                topic="phase check",
                audience="test readers",
                tone="technical",
                adk_session_id="phase-check-session",
            )
            assert blog.status == BlogSessionStatus.QUEUED
            assert blog.job_phase == "fresh_generation"
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
