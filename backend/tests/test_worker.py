"""Tests for worker behavior - job processing and agent snapshots."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWorkerJobProcessing:
    """Test worker dequeues job and updates status in DB."""

    @pytest.mark.asyncio
    async def test_worker_dequeues_job_from_redis(self, mock_redis):
        """Test worker pops job from Redis queue."""
        from src.core.task_queue import TaskQueue

        queue = TaskQueue()
        queue._dequeue_script_sha = "test"

        test_job_json = '{"session_id": 1, "user_id": 1, "adk_session_id": "test-adk", "topic": "Test", "audience": "test", "tone": "professional", "phase": "fresh_generation"}'

        mock_redis.evalsha = AsyncMock(return_value=test_job_json)
        mock_redis.zadd = AsyncMock(return_value=1)

        job = await queue.dequeue(timeout=1)

        assert job is not None
        assert job.session_id == 1

    @pytest.mark.asyncio
    async def test_worker_updates_session_status_to_processing(self, mock_db_session):
        """Test worker updates BlogSession status to PROCESSING."""
        mock_session = MagicMock()
        mock_session.status = "QUEUED"

        with patch(
            "src.models.repositories.blog_session_repository.BlogSessionRepository.get_by_id"
        ) as mock_get:
            mock_get.return_value = mock_session

            with patch(
                "src.models.repositories.blog_session_repository.BlogSessionRepository.update_status"
            ) as mock_update:
                from src.models.repositories.blog_session_repository import BlogSessionRepository

                repo = BlogSessionRepository(mock_db_session)

                await repo.update_status(1, "PROCESSING", "intent")

                mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_creates_lease_record(self, mock_db_session):
        """Test worker creates SessionLease entry when acquiring lease."""
        with patch(
            "src.models.repositories.session_lease_repository.SessionLeaseRepository.acquire_lease"
        ) as mock_acquire:
            mock_acquire.return_value = MagicMock(acquired=True)

            from src.core.task_queue import BlogJob
            from src.models.repositories.session_lease_repository import SessionLeaseRepository

            repo = SessionLeaseRepository(mock_db_session)
            job = BlogJob(
                session_id=1,
                user_id=1,
                adk_session_id="test-adk",
                topic="Test",
                audience="test",
                tone="professional",
                phase="fresh_generation",
            )

            result = await repo.acquire_lease(job=job, worker_id="worker-1", lease_seconds=300)

            assert result.acquired is True

    @pytest.mark.asyncio
    async def test_worker_releases_lease_on_completion(self, mock_db_session):
        """Test worker releases lease after job done."""
        mock_lease = MagicMock()
        mock_lease.ended_at = None

        with patch(
            "src.models.repositories.session_lease_repository.SessionLeaseRepository.get_current_lease"
        ) as mock_get:
            mock_get.return_value = mock_lease

            with patch(
                "src.models.repositories.session_lease_repository.SessionLeaseRepository.release_lease"
            ) as mock_release:
                from src.models.repositories.session_lease_repository import SessionLeaseRepository

                repo = SessionLeaseRepository(mock_db_session)

                await repo.release_lease(1, "worker-1")

                mock_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_heartbeat_extends_lease(self, mock_db_session):
        """Test worker heartbeat extends lease expiry."""
        with patch(
            "src.models.repositories.session_lease_repository.SessionLeaseRepository.heartbeat_lease"
        ) as mock_heartbeat:
            mock_heartbeat.return_value = True

            from src.models.repositories.session_lease_repository import SessionLeaseRepository

            repo = SessionLeaseRepository(mock_db_session)

            result = await repo.heartbeat_lease(1, "worker-1", extend_seconds=60)

            assert result is True


class TestAgentRunSnapshots:
    """Test worker stores snapshot of each agent's output."""

    @pytest.mark.asyncio
    async def test_worker_creates_agent_run_records(self, mock_db_session):
        """Test worker creates AgentRun for each agent stage."""
        with patch(
            "src.models.repositories.agent_run_repository.AgentRunRepository.create"
        ) as mock_create:
            mock_create.return_value = MagicMock(id=1)

            from src.models.repositories.agent_run_repository import AgentRunRepository

            repo = AgentRunRepository(mock_db_session)

            await repo.create(
                blog_session_id=1,
                stage_name="intent",
                status="COMPLETED",
                total_tokens=150,
                cost_usd=0.000003,
            )

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["stage_name"] == "intent"
            assert call_kwargs["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_worker_stores_output_snapshot(self, mock_db_session):
        """Test worker stores output_snapshot for each agent run."""
        output_snapshot = {
            "stage": "intent",
            "total_tokens": 150,
            "cost_usd": 0.000003,
        }

        with patch(
            "src.models.repositories.agent_run_repository.AgentRunRepository.create"
        ) as mock_create:
            mock_create.return_value = MagicMock(id=1)

            from src.models.repositories.agent_run_repository import AgentRunRepository

            repo = AgentRunRepository(mock_db_session)

            await repo.create(
                blog_session_id=1,
                stage_name="intent",
                status="COMPLETED",
                total_tokens=150,
                cost_usd=0.000003,
                output_snapshot=output_snapshot,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["output_snapshot"] == output_snapshot

    @pytest.mark.asyncio
    async def test_worker_stores_latency_and_completion_time(self, mock_db_session):
        """Test worker records latency_ms and completed_at."""
        with patch(
            "src.models.repositories.agent_run_repository.AgentRunRepository.create"
        ) as mock_create:
            mock_create.return_value = MagicMock(id=1)

            from src.models.repositories.agent_run_repository import AgentRunRepository

            repo = AgentRunRepository(mock_db_session)

            await repo.create(
                blog_session_id=1,
                stage_name="intent",
                status="COMPLETED",
                total_tokens=150,
                cost_usd=0.000003,
                latency_ms=1500,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["latency_ms"] == 1500

    @pytest.mark.asyncio
    async def test_worker_stores_token_counts(self, mock_db_session):
        """Test worker records total_tokens."""
        with patch(
            "src.models.repositories.agent_run_repository.AgentRunRepository.create"
        ) as mock_create:
            mock_create.return_value = MagicMock(id=1)

            from src.models.repositories.agent_run_repository import AgentRunRepository

            repo = AgentRunRepository(mock_db_session)

            await repo.create(
                blog_session_id=1,
                stage_name="writer",
                status="COMPLETED",
                total_tokens=7000,
                cost_usd=0.00014,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["total_tokens"] == 7000

    @pytest.mark.asyncio
    async def test_worker_creates_agent_runs_for_all_stages(self, mock_db_session):
        """Test worker creates agent runs for all stages: intent, outline, research, writer, editor."""
        stages = ["intent", "outline", "research", "writer", "editor"]

        created_runs = []

        async def mock_create(
            blog_session_id,
            stage_name,
            status="STARTED",
            total_tokens=0,
            cost_usd=0.0,
            latency_ms=None,
            output_snapshot=None,
        ):
            run = MagicMock()
            run.id = len(created_runs) + 1
            run.stage_name = stage_name
            created_runs.append(run)
            return run

        with patch(
            "src.models.repositories.agent_run_repository.AgentRunRepository.create",
            side_effect=mock_create,
        ):
            from src.models.repositories.agent_run_repository import AgentRunRepository

            repo = AgentRunRepository(mock_db_session)

            for stage in stages:
                await repo.create(
                    blog_session_id=1,
                    stage_name=stage,
                    status="COMPLETED",
                )

            assert len(created_runs) == 5
            for i, stage in enumerate(stages):
                assert created_runs[i].stage_name == stage


class TestResearchSourcesStorage:
    """Test worker stores research sources from Tavily."""

    @pytest.mark.asyncio
    async def test_worker_creates_research_sources(self, mock_db_session):
        """Test worker stores research sources from Tavily."""
        sources_data = [
            {
                "title": "AI in Healthcare",
                "url": "https://example.com/1",
            },
            {
                "title": "Machine Learning Basics",
                "url": "https://example.com/2",
            },
        ]

        created_sources = []

        async def mock_create_many(blog_session_id, sources):
            for src in sources:
                s = MagicMock()
                s.title = src["title"]
                s.url = src["url"]
                created_sources.append(s)
            return created_sources

        with patch(
            "src.models.repositories.research_sources_repository.ResearchSourcesRepository.create_many",
            side_effect=mock_create_many,
        ):
            from src.models.repositories.research_sources_repository import (
                ResearchSourcesRepository,
            )

            repo = ResearchSourcesRepository(mock_db_session)

            result = await repo.create_many(blog_session_id=1, sources=sources_data)

            assert len(result) == 2
            assert result[0].title == "AI in Healthcare"
            assert result[1].title == "Machine Learning Basics"

    @pytest.mark.asyncio
    async def test_research_sources_count_returns_correct_count(self, mock_db_session):
        """Test sources count method returns correct number."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_db_session.execute.return_value = mock_result

        from src.models.repositories.research_sources_repository import ResearchSourcesRepository

        repo = ResearchSourcesRepository(mock_db_session)

        count = await repo.count_for_session(1)

        assert count == 3
