"""Database-backed outbox for durable workflow dispatch."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import WorkflowOutboxEvent


class WorkflowOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        event_type: str,
        aggregate_id: int,
        payload: dict,
    ) -> WorkflowOutboxEvent:
        event = WorkflowOutboxEvent(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_dispatchable(self, *, limit: int = 100, republish_after_seconds: int = 300):
        """Rows that need a Redis delivery or whose worker lease expired."""
        now = datetime.now(timezone.utc)
        republish_before = now - timedelta(seconds=republish_after_seconds)
        undispatched_before = now - timedelta(seconds=30)
        stmt = (
            select(WorkflowOutboxEvent)
            .where(
                WorkflowOutboxEvent.available_at <= now,
                or_(
                    and_(
                        WorkflowOutboxEvent.status == "PENDING",
                        or_(
                            and_(
                                WorkflowOutboxEvent.dispatched_at.is_(None),
                                WorkflowOutboxEvent.created_at <= undispatched_before,
                            ),
                            WorkflowOutboxEvent.dispatched_at <= republish_before,
                        ),
                    ),
                    and_(
                        WorkflowOutboxEvent.status == "PROCESSING",
                        WorkflowOutboxEvent.locked_until <= now,
                    ),
                ),
            )
            .order_by(WorkflowOutboxEvent.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_undispatched_for_aggregate(
        self, aggregate_id: int
    ) -> WorkflowOutboxEvent | None:
        stmt = (
            select(WorkflowOutboxEvent)
            .where(
                WorkflowOutboxEvent.aggregate_id == aggregate_id,
                WorkflowOutboxEvent.status == "PENDING",
                WorkflowOutboxEvent.dispatched_at.is_(None),
            )
            .order_by(WorkflowOutboxEvent.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_dispatched(self, event_id: int) -> None:
        result = await self._session.execute(
            select(WorkflowOutboxEvent)
            .where(WorkflowOutboxEvent.id == event_id)
            .with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is not None and event.status in {"PENDING", "PROCESSING"}:
            event.dispatched_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def claim_event(
        self, event_id: int, *, worker_id: str, lease_seconds: int = 300
    ) -> WorkflowOutboxEvent | None:
        now = datetime.now(timezone.utc)
        stmt = (
            select(WorkflowOutboxEvent)
            .where(
                WorkflowOutboxEvent.id == event_id,
                WorkflowOutboxEvent.available_at <= now,
                or_(
                    WorkflowOutboxEvent.status == "PENDING",
                    and_(
                        WorkflowOutboxEvent.status == "PROCESSING",
                        WorkflowOutboxEvent.locked_until <= now,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        event = (await self._session.execute(stmt)).scalar_one_or_none()
        if event is None:
            return None
        event.status = "PROCESSING"
        event.attempts += 1
        event.locked_by = worker_id
        event.locked_until = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return event

    async def heartbeat(
        self,
        event_id: int,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        event = await self._owned_event(event_id, worker_id)
        if event is None:
            return False
        event.locked_until = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        await self._session.flush()
        return True

    async def complete(self, event_id: int, *, worker_id: str) -> bool:
        event = await self._owned_event(event_id, worker_id)
        if event is None:
            return False
        event.status = "PROCESSED"
        event.processed_at = datetime.now(timezone.utc)
        event.locked_by = None
        event.locked_until = None
        await self._session.flush()
        return True

    async def fail(self, event_id: int, *, worker_id: str, error: str) -> bool:
        event = await self._owned_event(event_id, worker_id)
        if event is None:
            return False
        event.status = "FAILED"
        event.last_error = error[:4000]
        event.locked_by = None
        event.locked_until = None
        await self._session.flush()
        return True

    async def retry(
        self, event_id: int, *, worker_id: str, error: str, max_attempts: int = 4
    ) -> bool:
        event = await self._owned_event(event_id, worker_id)
        if event is None:
            return False
        if event.attempts >= max_attempts:
            event.status = "FAILED"
            event.last_error = error[:4000]
            event.locked_by = None
            event.locked_until = None
            await self._session.flush()
            return False
        delay = min(2 ** min(event.attempts, 8), 300)
        event.status = "PENDING"
        event.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        event.dispatched_at = None
        event.locked_by = None
        event.locked_until = None
        event.last_error = error[:4000]
        await self._session.flush()
        return True

    async def _owned_event(self, event_id: int, worker_id: str) -> WorkflowOutboxEvent | None:
        result = await self._session.execute(
            select(WorkflowOutboxEvent).where(
                WorkflowOutboxEvent.id == event_id,
                WorkflowOutboxEvent.status == "PROCESSING",
                WorkflowOutboxEvent.locked_by == worker_id,
            )
        )
        return result.scalar_one_or_none()
