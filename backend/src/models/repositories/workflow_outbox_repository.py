"""Database-backed outbox for durable workflow dispatch."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import WorkflowOutboxEvent
from src.monitoring.tracing import inject_trace_context


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
        durable_payload = dict(payload)
        trace_context = inject_trace_context()
        if trace_context:
            durable_payload.setdefault("trace_context", trace_context)
        event = WorkflowOutboxEvent(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=durable_payload,
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

    async def fail_exhausted_expired_claims(self, *, max_attempts: int = 4) -> list[int]:
        """Fail expired claims after the initial attempt plus bounded retries."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(WorkflowOutboxEvent)
            .where(
                WorkflowOutboxEvent.status == "PROCESSING",
                WorkflowOutboxEvent.locked_until <= now,
                WorkflowOutboxEvent.attempts >= max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
        events = list((await self._session.execute(stmt)).scalars().all())
        session_ids = []
        for event in events:
            event.status = "FAILED"
            event.last_error = "worker claim expired after maximum attempts"
            event.locked_by = None
            event.locked_until = None
            session_ids.append(event.aggregate_id)
        if events:
            await self._session.flush()
        return session_ids

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

    async def get_delivery_state(
        self, event_id: int
    ) -> tuple[str, datetime | None, datetime] | None:
        """Return durable state after a delivery could not claim its event.

        This distinguishes an already-owned/terminal duplicate from a pending
        event whose Redis message must be delivered again.
        """
        result = await self._session.execute(
            select(
                WorkflowOutboxEvent.status,
                WorkflowOutboxEvent.locked_until,
                WorkflowOutboxEvent.available_at,
            ).where(WorkflowOutboxEvent.id == event_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row.status, row.locked_until, row.available_at

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
