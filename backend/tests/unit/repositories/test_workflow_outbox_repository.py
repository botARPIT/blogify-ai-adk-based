"""Unit coverage for outbox ownership and retry state transitions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository


def session_with_row(row):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def event(*, status="PENDING", attempts=0, locked_by=None):
    from src.models.orm_models import WorkflowOutboxEvent

    return WorkflowOutboxEvent(
        event_type="blog.continue_generation",
        aggregate_id=21,
        payload={"session_id": 21},
        status=status,
        attempts=attempts,
        locked_by=locked_by,
    )


@pytest.mark.asyncio
async def test_enqueue_adds_durable_event_and_flushes(mock_db_session):
    repository = WorkflowOutboxRepository(mock_db_session)

    result = await repository.enqueue(
        event_type="blog.continue_generation",
        aggregate_id=21,
        payload={"session_id": 21},
    )

    assert result.aggregate_id == 21
    assert result.event_type == "blog.continue_generation"
    assert result.payload == {"session_id": 21}
    mock_db_session.add.assert_called_once_with(result)
    mock_db_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_event_assigns_owner_and_lease():
    row = event()
    session = session_with_row(row)
    repository = WorkflowOutboxRepository(session)

    claimed = await repository.claim_event(8, worker_id="worker-a", lease_seconds=45)

    assert claimed is row
    assert row.status == "PROCESSING"
    assert row.attempts == 1
    assert row.locked_by == "worker-a"
    assert row.locked_until is not None
    assert row.locked_until > datetime.now(timezone.utc) + timedelta(seconds=40)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_event_returns_none_when_another_transaction_holds_it():
    session = session_with_row(None)

    claimed = await WorkflowOutboxRepository(session).claim_event(8, worker_id="worker-b")

    assert claimed is None
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_state_returns_claim_and_retry_deadlines():
    session = AsyncMock()
    result = MagicMock()
    available_at = datetime.now(timezone.utc)
    locked_until = available_at + timedelta(seconds=30)
    result.one_or_none.return_value = MagicMock(
        status="PROCESSING", locked_until=locked_until, available_at=available_at
    )
    session.execute = AsyncMock(return_value=result)

    state = await WorkflowOutboxRepository(session).get_delivery_state(8)

    assert state == ("PROCESSING", locked_until, available_at)


@pytest.mark.asyncio
async def test_expired_claims_at_attempt_limit_are_failed():
    row = event(status="PROCESSING", attempts=4, locked_by="worker-a")
    row.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()

    failed_sessions = await WorkflowOutboxRepository(session).fail_exhausted_expired_claims()

    assert failed_sessions == [21]
    assert row.status == "FAILED"
    assert row.last_error == "worker claim expired after maximum attempts"
    assert row.locked_by is None
    assert row.locked_until is None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_requeues_with_backoff_and_clears_dispatch_lease():
    row = event(status="PROCESSING", attempts=2, locked_by="worker-a")
    row.dispatched_at = datetime.now(timezone.utc)
    session = session_with_row(row)

    retried = await WorkflowOutboxRepository(session).retry(
        8, worker_id="worker-a", error="temporary failure"
    )

    assert retried is True
    assert row.status == "PENDING"
    assert row.available_at >= datetime.now(timezone.utc) + timedelta(seconds=3)
    assert row.available_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert row.dispatched_at is None
    assert row.locked_by is None
    assert row.locked_until is None
    assert row.last_error == "temporary failure"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_at_attempt_limit_marks_event_failed():
    row = event(status="PROCESSING", attempts=4, locked_by="worker-a")
    session = session_with_row(row)

    retried = await WorkflowOutboxRepository(session).retry(
        8, worker_id="worker-a", error="provider unavailable", max_attempts=4
    )

    assert retried is False
    assert row.status == "FAILED"
    assert row.last_error == "provider unavailable"
    assert row.locked_by is None
    assert row.locked_until is None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_cannot_complete_an_event_it_does_not_own():
    session = session_with_row(None)

    completed = await WorkflowOutboxRepository(session).complete(8, worker_id="worker-b")

    assert completed is False
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_dispatched_does_not_change_terminal_event():
    row = event(status="PROCESSED")
    row.dispatched_at = None
    session = session_with_row(row)

    await WorkflowOutboxRepository(session).mark_dispatched(8)

    assert row.dispatched_at is None
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_for_owning_worker():
    row = event(status="PROCESSING", attempts=1, locked_by="worker-a")
    row.locked_until = datetime.now(timezone.utc)
    session = session_with_row(row)

    extended = await WorkflowOutboxRepository(session).heartbeat(
        8, worker_id="worker-a", lease_seconds=60
    )

    assert extended is True
    assert row.locked_until > datetime.now(timezone.utc) + timedelta(seconds=50)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_marks_event_processed_and_releases_lease():
    row = event(status="PROCESSING", attempts=1, locked_by="worker-a")
    session = session_with_row(row)

    completed = await WorkflowOutboxRepository(session).complete(8, worker_id="worker-a")

    assert completed is True
    assert row.status == "PROCESSED"
    assert row.processed_at is not None
    assert row.locked_by is None
    assert row.locked_until is None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_fail_records_bounded_error_and_releases_lease():
    row = event(status="PROCESSING", attempts=4, locked_by="worker-a")
    session = session_with_row(row)

    failed = await WorkflowOutboxRepository(session).fail(
        8, worker_id="worker-a", error="x" * 5000
    )

    assert failed is True
    assert row.status == "FAILED"
    assert len(row.last_error) == 4000
    assert row.locked_by is None
    assert row.locked_until is None
    session.flush.assert_awaited_once()
