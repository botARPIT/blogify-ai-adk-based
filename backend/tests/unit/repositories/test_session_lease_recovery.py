from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.task_queue import BlogJob
from src.models.orm_models import LeaseEventType
from src.models.repositories.session_lease_repository import SessionLeaseRepository


@pytest.mark.asyncio
async def test_expired_outbox_recovery_allows_reclaiming_session_lease():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    repository = SessionLeaseRepository(session)
    blog_session = SimpleNamespace(
        id=19,
        status="PROCESSING",
        current_stage="writer",
        updated_at=None,
        active_blog_version_id=7,
    )
    old_lease = SimpleNamespace(
        lease_owner="dead-worker",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        lease_version=2,
        ended_at=None,
        release_reason=None,
    )
    active_version = SimpleNamespace(id=7)
    job = BlogJob(
        session_id=19,
        user_id=4,
        adk_session_id="adk-19",
        topic="Lease recovery",
        audience="engineers",
        tone="technical",
        phase="fresh_generation",
    )
    repository._session_repo.get_by_id_for_update = AsyncMock(return_value=blog_session)
    repository._get_active_lease = AsyncMock(return_value=old_lease)
    repository._resolve_active_version = AsyncMock(return_value=active_version)
    repository._mark_processing = AsyncMock()
    repository._hydrate_job = MagicMock(return_value=job)

    result = await repository.acquire_lease(job, worker_id="new-worker", lease_seconds=300)

    assert result.acquired is True
    assert old_lease.ended_at is not None
    assert old_lease.release_reason == LeaseEventType.HEARTBEAT_FAILED
    assert blog_session.status == "QUEUED"
    assert blog_session.current_stage == "requeued_by_outbox"
    new_lease = session.add.call_args.args[0]
    assert new_lease.lease_owner == "new-worker"
    assert new_lease.lease_version == 3
