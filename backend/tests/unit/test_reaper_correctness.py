from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class _AsyncSessionContext:
    def __init__(self, session=None) -> None:
        self.session = session or SimpleNamespace()
        self.session.begin = self.begin

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @asynccontextmanager
    async def begin(self):
        yield self.session


@pytest.mark.asyncio
async def test_reaper_requeues_only_sessions_reaped_in_current_cycle():
    from src.core import job_reaper as job_reaper_module

    stale_session = SimpleNamespace(
        id=101,
        owned_by="worker-a",
        lease_version=1,
        reap_count=0,
        current_stage="writer",
        topic="Topic",
        audience="developers",
        end_user_id=11,
    )
    fake_repo = SimpleNamespace(
        find_stale_processing=AsyncMock(return_value=[stale_session]),
        reap_session=AsyncMock(return_value=2),
        update_status=AsyncMock(),
    )

    with (
        patch.object(job_reaper_module, "get_session_factory", return_value=lambda: _AsyncSessionContext()),
        patch.object(job_reaper_module, "BlogSessionRepository", return_value=fake_repo),
        patch.object(job_reaper_module.task_queue, "enqueue", new=AsyncMock()) as enqueue,
    ):
        reaped = await job_reaper_module.JobReaper()._reap_cycle()

    assert reaped == 1
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["payload"]["canonical_session_id"] == 101
