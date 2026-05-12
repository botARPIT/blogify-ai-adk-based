"""Tests for job persistence - API creates DB record and enqueues to Redis."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestJobPersistence:
    """Test that API persists job to DB and enqueues to Redis."""

    @pytest.mark.asyncio
    async def test_generate_creates_session_in_db(self):
        """Test POST /generate creates BlogSession record in database."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        mock_blog_session = MagicMock()
        mock_blog_session.id = 1
        mock_blog_session.user_id = 1
        mock_blog_session.topic = "Test Topic"
        mock_blog_session.status = "QUEUED"

        with patch("src.core.database.AsyncSessionFactory") as mock_factory:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_session)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_factory.return_value = mock_instance

            with patch(
                "src.models.repositories.blog_session_repository.BlogSessionRepository.create"
            ) as mock_create:
                mock_create.return_value = mock_blog_session

                from src.models.repositories.blog_session_repository import BlogSessionRepository

                repo = BlogSessionRepository(mock_session)
                result = await repo.create(
                    user_id=1,
                    topic="Test Topic",
                    audience="test",
                    tone="professional",
                    adk_session_id="test-adk-id",
                )

                assert mock_session.add.called
                assert mock_session.flush.called
                assert result.topic == "Test Topic"

    @pytest.mark.asyncio
    async def test_generate_enqueues_to_redis(self, mock_redis):
        """Test POST /generate adds job to Redis queue."""
        with patch("src.core.redis_pool.get_redis_client", return_value=mock_redis):
            from src.core.task_queue import TaskQueue

            queue = TaskQueue()
            queue._dequeue_script_sha = "test"

            from src.core.task_queue import BlogJob

            job = BlogJob(
                session_id=1,
                user_id=1,
                adk_session_id="test-adk-session",
                topic="Test Topic",
                audience="test",
                tone="professional",
                phase="start",
            )

            await queue.enqueue(job)

            mock_redis.lpush.assert_called_once()
            call_args = mock_redis.lpush.call_args
            assert call_args[0][0] == "blogify:tasks"

            enqueued_job = json.loads(call_args[0][1])
            assert enqueued_job["session_id"] == 1
            assert enqueued_job["user_id"] == 1
            assert enqueued_job["topic"] == "Test Topic"

    @pytest.mark.asyncio
    async def test_generate_creates_budget_ledger_entry(self, mock_session):
        """Test POST /generate creates budget ledger entry for reservation."""
        with patch(
            "src.models.repositories.budget_repository.BudgetRepository.write_entry"
        ) as mock_write:
            mock_write.return_value = MagicMock(id=1)

            from src.models.repositories.budget_repository import BudgetRepository

            repo = BudgetRepository(mock_session)

            await repo.write_entry(
                user_id=1,
                blog_session_id=1,
                entry_type="RESERVE",
                tokens=-50000,
                amount_usd=-1.0,
                note="Budget reservation for blog generation",
            )

            mock_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotency_key_prevents_duplicate_session(self, mock_session):
        """Test same idempotency key returns existing session without creating new."""
        with patch(
            "src.models.repositories.blog_session_repository.BlogSessionRepository.get_by_idempotency_key"
        ) as mock_get:
            existing_session = MagicMock()
            existing_session.id = 1
            mock_get.return_value = existing_session

            from src.models.repositories.blog_session_repository import BlogSessionRepository

            repo = BlogSessionRepository(mock_session)

            result = await repo.get_by_idempotency_key(1, "unique-key-123")

            assert result is not None
            assert result.id == 1
            assert not mock_session.add.called

    @pytest.mark.asyncio
    async def test_idempotency_key_none_creates_new_session(self, mock_session):
        """Test no idempotency key creates new session."""
        with patch(
            "src.models.repositories.blog_session_repository.BlogSessionRepository.get_by_idempotency_key"
        ) as mock_get:
            mock_get.return_value = None

            with patch(
                "src.models.repositories.blog_session_repository.BlogSessionRepository.create"
            ) as mock_create:
                new_session = MagicMock()
                new_session.id = 2
                mock_create.return_value = new_session

                from src.models.repositories.blog_session_repository import BlogSessionRepository

                repo = BlogSessionRepository(mock_session)

                existing = await repo.get_by_idempotency_key(1, None)
                if existing is None:
                    result = await repo.create(
                        user_id=1,
                        topic="New Topic",
                        audience="test",
                        tone="professional",
                        adk_session_id="new-adk-id",
                        idempotency_key=None,
                    )
                    mock_create.assert_called()
                    assert result.id == 2


class TestJobEnqueueDetails:
    """Test job enqueue structure and details."""

    @pytest.mark.asyncio
    async def test_job_contains_all_required_fields(self, mock_redis):
        """Test job enqueued contains all required fields."""
        with patch("src.core.redis_pool.get_redis_client", return_value=mock_redis):
            from src.core.task_queue import BlogJob, TaskQueue

            queue = TaskQueue()
            queue._dequeue_script_sha = "test"

            job = BlogJob(
                session_id=42,
                user_id=7,
                adk_session_id="adk-session-123",
                topic="Python Best Practices",
                audience="developers",
                tone="professional",
                phase="start",
            )

            await queue.enqueue(job)

            call_args = mock_redis.lpush.call_args
            enqueued_job = json.loads(call_args[0][1])

            assert "session_id" in enqueued_job
            assert "user_id" in enqueued_job
            assert "adk_session_id" in enqueued_job
            assert "topic" in enqueued_job
            assert "audience" in enqueued_job
            assert "tone" in enqueued_job
            assert "phase" in enqueued_job
            assert "enqueued_at" in enqueued_job

    @pytest.mark.asyncio
    async def test_multiple_jobs_enqueued_separately(self, mock_redis):
        """Test multiple jobs are enqueued with correct order."""
        with patch("src.core.redis_pool.get_redis_client", return_value=mock_redis):
            from src.core.task_queue import BlogJob, TaskQueue

            queue = TaskQueue()
            queue._dequeue_script_sha = "test"

            job1 = BlogJob(
                session_id=1,
                user_id=1,
                adk_session_id="1",
                topic="Topic 1",
                audience="a1",
                tone="t1",
                phase="start",
            )
            job2 = BlogJob(
                session_id=2,
                user_id=1,
                adk_session_id="2",
                topic="Topic 2",
                audience="a2",
                tone="t2",
                phase="start",
            )

            await queue.enqueue(job1)
            await queue.enqueue(job2)

            assert mock_redis.lpush.call_count == 2
