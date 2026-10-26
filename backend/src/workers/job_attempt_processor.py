"""Durable coordination for one queued workflow attempt.

This module owns the database, outbox, and lease protocol. The worker itself
only consumes queue messages and limits concurrency.
"""

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory
from src.core.task_queue import BlogJob, TaskQueue
from src.models.orm_models import BlogSessionStatus
from src.models.repositories.blog_session_repository import BlogSessionRepository
from src.models.repositories.blog_version_repository import BlogVersionRepository
from src.models.repositories.session_lease_repository import SessionLeaseRepository
from src.models.repositories.workflow_outbox_repository import WorkflowOutboxRepository
from src.monitoring.metrics import (
    worker_job_duration_seconds,
    worker_jobs_in_progress,
    worker_jobs_total,
)
from src.monitoring.tracing import extract_trace_context, record_current_exception, trace_span
from src.services.exceptions import WorkflowOwnershipLostError
from src.services.workflow_result_persister import WorkflowResultPersister

logger = get_logger(__name__)
HEARTBEAT_INTERVAL = 30
LEASE_SECONDS = 300


class WorkflowAttemptProcessor:
    """Claim, execute, and durably finish a single queue delivery."""

    def __init__(self, queue: TaskQueue, worker_id: str) -> None:
        self._queue = queue
        self._worker_id = worker_id

    async def process(self, delivery: BlogJob) -> None:
        started_at = time.perf_counter()
        phase = delivery.phase
        worker_jobs_in_progress.labels(phase=phase).inc()
        context = extract_trace_context(delivery.trace_context)
        try:
            with trace_span(
                "blog.job.process",
                {
                    "blog.session_id": delivery.session_id,
                    "blog.phase": delivery.phase,
                    "messaging.message.id": delivery.outbox_event_id or "unknown",
                },
                context=context,
            ):
                await self._process(delivery)
        finally:
            worker_jobs_in_progress.labels(phase=phase).dec()
            worker_job_duration_seconds.labels(phase=phase).observe(
                time.perf_counter() - started_at
            )

    async def _process(self, delivery: BlogJob) -> None:
        phase = delivery.phase
        owner = f"{self._worker_id}:{uuid.uuid4()}"
        event_id = delivery.outbox_event_id
        job = delivery
        if event_id is not None:
            job = await self._hydrate_job(delivery, event_id, owner)
            if job is None:
                return
        hydrated = await self._acquire_lease(job, delivery, event_id, owner)
        if hydrated is None:
            return
        # Import the ADK-facing executor only for an acquired attempt. This
        # keeps queue/outbox recovery code importable in lightweight tooling.
        from src.workers.executor import RetryableDownstreamError, WorkflowExecutor

        heartbeat = asyncio.create_task(self._job_heartbeat(hydrated))
        try:
            result = await WorkflowExecutor().execute(hydrated)
            async with AsyncSessionFactory() as session:
                await WorkflowResultPersister(session).persist_success(hydrated, result)
                await session.commit()
            worker_jobs_total.labels(phase=phase, outcome="succeeded").inc()
            await self._queue.acknowledge(delivery)
        except WorkflowOwnershipLostError as exc:
            worker_jobs_total.labels(phase=phase, outcome="stale").inc()
            logger.warning(
                "stale_workflow_result_discarded", session_id=job.session_id, error=str(exc)
            )
            await self._queue.acknowledge(delivery)
        except Exception as exc:
            record_current_exception(exc)
            logger.error("job_failed", session_id=job.session_id, error=str(exc))
            retried = (
                event_id is not None
                and isinstance(exc, RetryableDownstreamError)
                and await self._schedule_retry(hydrated, str(exc))
            )
            if retried:
                worker_jobs_total.labels(phase=phase, outcome="retried").inc()
            else:
                persisted = await self._persist_failure(hydrated, str(exc))
                outcome = "failed" if persisted else "stale"
                worker_jobs_total.labels(phase=phase, outcome=outcome).inc()
            await self._queue.acknowledge(delivery)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await self._release_lease(hydrated)

    async def _hydrate_job(self, delivery: BlogJob, event_id: int, owner: str) -> BlogJob | None:
        try:
            payload = await self._claim_event(event_id, owner)
            if payload is None:
                await self._handle_unclaimed_delivery(delivery, event_id)
                return None
            data = dict(payload["job"])
            data.update(outbox_event_id=event_id, trace_context=payload.get("trace_context"))
            return BlogJob(**data)
        except (KeyError, TypeError, ValueError) as exc:
            error = f"invalid job payload: {exc}"
            if not await self._retry_event(event_id, owner, error):
                await self._fail_event(event_id, owner, error)
            await self._queue.acknowledge(delivery)
            return None

    async def _claim_event(self, event_id: int, owner: str) -> dict[str, Any] | None:
        async with AsyncSessionFactory() as session:
            event = await WorkflowOutboxRepository(session).claim_event(
                event_id, worker_id=owner, lease_seconds=LEASE_SECONDS
            )
            if event is None:
                await session.rollback()
                return None
            payload = dict(event.payload)
            await session.commit()
            return payload

    async def _acquire_lease(
        self,
        job: BlogJob,
        delivery: BlogJob,
        event_id: int | None,
        owner: str,
    ) -> BlogJob | None:
        async with AsyncSessionFactory() as session:
            if event_id is not None:
                blog_session = await BlogSessionRepository(session).get_by_id(job.session_id)
                valid_status = blog_session and blog_session.status in {
                    BlogSessionStatus.QUEUED.value,
                    BlogSessionStatus.PROCESSING.value,
                }
                valid_phase = blog_session and (
                    blog_session.status != BlogSessionStatus.QUEUED.value
                    or blog_session.job_phase == job.phase
                )
                if not valid_status or not valid_phase:
                    await session.rollback()
                    await self._complete_event(event_id, owner)
                    await self._queue.acknowledge(delivery)
                    return None
            acquired = await SessionLeaseRepository(session).acquire_lease(
                job, owner, LEASE_SECONDS
            )
            if not acquired.acquired or acquired.job is None:
                await session.rollback()
                if event_id is not None:
                    await self._retry_event(
                        event_id, owner, "session lease is currently held by another worker"
                    )
                await self._queue.acknowledge(delivery)
                return None
            acquired.job.outbox_event_id = event_id
            await session.commit()
            return acquired.job

    async def _persist_failure(self, job: BlogJob, error: str) -> bool:
        try:
            async with AsyncSessionFactory() as session:
                await WorkflowResultPersister(session).persist_failure(job, error)
                await session.commit()
            return True
        except WorkflowOwnershipLostError as exc:
            logger.warning(
                "stale_workflow_failure_discarded", session_id=job.session_id, error=str(exc)
            )
            return False

    async def _job_heartbeat(self, job: BlogJob) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                async with AsyncSessionFactory() as session:
                    lease_ok = await SessionLeaseRepository(session).heartbeat_lease(
                        job.session_id,
                        job.lease_owner or "",
                        job.lease_version or 0,
                        extend_seconds=90,
                    )
                    outbox_ok = job.outbox_event_id is None or await WorkflowOutboxRepository(
                        session
                    ).heartbeat(
                        job.outbox_event_id,
                        worker_id=job.lease_owner or "",
                        lease_seconds=LEASE_SECONDS,
                    )
                    if lease_ok and outbox_ok:
                        await session.commit()
                    else:
                        await session.rollback()
            except Exception:
                logger.debug("workflow_heartbeat_failed", session_id=job.session_id, exc_info=True)

    async def _handle_unclaimed_delivery(self, job: BlogJob, event_id: int) -> None:
        try:
            async with AsyncSessionFactory() as session:
                state = await WorkflowOutboxRepository(session).get_delivery_state(event_id)
                await session.rollback()
        except Exception as exc:
            logger.warning("outbox_claim_state_lookup_failed", event_id=event_id, error=str(exc))
            return
        if state is None:
            await self._queue.acknowledge(job)
            return
        status, locked_until, available_at = state
        now = datetime.now(timezone.utc)
        if (
            status in {"PROCESSED", "FAILED"}
            or (status == "PROCESSING" and locked_until and locked_until > now)
            or available_at > now
        ):
            await self._queue.acknowledge(job)
            return
        await self._queue.enqueue(job)
        await self._queue.acknowledge(job)
        logger.warning(
            "outbox_delivery_requeued_after_unclaimed_event",
            event_id=event_id,
            session_id=job.session_id,
            event_status=status,
        )

    async def _complete_event(self, event_id: int, owner: str) -> None:
        async with AsyncSessionFactory() as session:
            await WorkflowOutboxRepository(session).complete(event_id, worker_id=owner)
            await session.commit()

    async def _retry_event(self, event_id: int, owner: str, error: str) -> bool:
        async with AsyncSessionFactory() as session:
            retried = await WorkflowOutboxRepository(session).retry(
                event_id, worker_id=owner, error=error
            )
            await session.commit()
            return retried

    async def _schedule_retry(self, job: BlogJob, error: str) -> bool:
        if job.outbox_event_id is None or not job.lease_owner or job.lease_version is None:
            return False
        async with AsyncSessionFactory() as session:
            outbox = WorkflowOutboxRepository(session)
            await outbox.lock_current_claim(
                event_id=job.outbox_event_id, claim_owner=job.lease_owner
            )
            if not await outbox.retry(job.outbox_event_id, worker_id=job.lease_owner, error=error):
                await session.commit()
                return False
            sessions = BlogSessionRepository(session)
            await sessions.get_by_id_for_update(job.session_id)
            await sessions.recover_stale_processing_session(
                job.session_id, current_stage="retry_scheduled"
            )
            versions = BlogVersionRepository(session)
            active = await versions.get_active_for_session(job.session_id, for_update=True)
            if active is not None:
                await versions.update_version_state(
                    active.id, status=BlogSessionStatus.QUEUED.value, job_phase=job.phase
                )
            await SessionLeaseRepository(session).release_lease(
                job.session_id, job.lease_owner, job.lease_version
            )
            await session.commit()
            return True

    async def _fail_event(self, event_id: int, owner: str, error: str) -> None:
        async with AsyncSessionFactory() as session:
            await WorkflowOutboxRepository(session).fail(event_id, worker_id=owner, error=error)
            await session.commit()

    async def _release_lease(self, job: BlogJob) -> None:
        try:
            async with AsyncSessionFactory() as session:
                await SessionLeaseRepository(session).release_lease(
                    job.session_id, job.lease_owner or "", job.lease_version or 0
                )
                await session.commit()
        except Exception as exc:
            logger.error("lease_release_failed", session_id=job.session_id, error=str(exc))
