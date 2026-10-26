from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.core.task_queue import BlogJob
from src.workers.job_attempt_processor import WorkflowAttemptProcessor


class FakeAsyncSessionContext:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture
def job():
    return BlogJob(
        session_id=19,
        user_id=4,
        adk_session_id="adk-19",
        topic="Outbox delivery",
        audience="engineers",
        tone="technical",
        phase="fresh_generation",
        outbox_event_id=23,
    )


@pytest.mark.asyncio
async def test_unclaimed_pending_event_is_requeued_before_ack(monkeypatch, job):
    from src.workers import job_attempt_processor as worker_module

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(worker_module, "AsyncSessionFactory", FakeAsyncSessionContext)
    monkeypatch.setattr(
        worker_module.WorkflowOutboxRepository,
        "get_delivery_state",
        AsyncMock(return_value=("PENDING", None, now - timedelta(seconds=1))),
    )
    queue = AsyncMock()
    worker = WorkflowAttemptProcessor(queue, "test-worker")

    await worker._handle_unclaimed_delivery(job, event_id=23)

    queue.enqueue.assert_awaited_once_with(job)
    queue.acknowledge.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_unclaimed_event_owned_by_live_worker_is_only_acked(monkeypatch, job):
    from src.workers import job_attempt_processor as worker_module

    locked_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    monkeypatch.setattr(worker_module, "AsyncSessionFactory", FakeAsyncSessionContext)
    monkeypatch.setattr(
        worker_module.WorkflowOutboxRepository,
        "get_delivery_state",
        AsyncMock(return_value=("PROCESSING", locked_until, datetime.now(timezone.utc))),
    )
    queue = AsyncMock()
    worker = WorkflowAttemptProcessor(queue, "test-worker")

    await worker._handle_unclaimed_delivery(job, event_id=23)

    queue.enqueue.assert_not_awaited()
    queue.acknowledge.assert_awaited_once_with(job)
