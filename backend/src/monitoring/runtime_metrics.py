"""Periodic snapshots of durable workflow, queue, and database state."""

import asyncio
import json
import time
from contextlib import suppress

from sqlalchemy import func, select, text

from src.config.logging_config import get_logger
from src.core.database import AsyncSessionFactory, engine
from src.core.redis_pool import get_redis_client
from src.core.task_queue import TaskQueue
from src.models.orm_models import BlogSession, BlogSessionStatus, WorkflowOutboxEvent
from src.monitoring.metrics import (
    blog_sessions_by_status,
    database_connections,
    database_deadlocks,
    database_max_connections,
    database_pool_connections,
    database_size_bytes,
    database_transactions,
    redis_queue_capacity,
    redis_queue_items,
    runtime_metrics_refresh_errors_total,
    runtime_metrics_refresh_success_timestamp_seconds,
    workers_active,
    workers_active_jobs,
    workers_capacity,
    workflow_outbox_events_by_status,
    workflow_outbox_oldest_pending_seconds,
)

logger = get_logger(__name__)


async def refresh_runtime_metrics(
    process_name: str, *, include_shared_state: bool
) -> bool:
    """Refresh SQLAlchemy pool gauges and, on the API, shared durable-state gauges."""
    update_database_pool_metrics(process_name)
    if not include_shared_state:
        return True

    refresh_ok = True
    try:
        await _refresh_postgres_state()
    except Exception:
        refresh_ok = False
        logger.warning("postgres_metrics_refresh_failed", process=process_name, exc_info=True)
    try:
        await _refresh_redis_state()
    except Exception:
        refresh_ok = False
        logger.warning("redis_metrics_refresh_failed", process=process_name, exc_info=True)
    return refresh_ok


async def _refresh_postgres_state() -> None:
    async with AsyncSessionFactory() as session:
        session_counts = (
            await session.execute(
                select(BlogSession.status, func.count()).group_by(BlogSession.status)
            )
        ).all()
        for status in BlogSessionStatus:
            blog_sessions_by_status.labels(status=status.value).set(0)
        for status, count in session_counts:
            blog_sessions_by_status.labels(status=str(status)).set(count)

        outbox_counts = (
            await session.execute(
                select(WorkflowOutboxEvent.status, func.count()).group_by(
                    WorkflowOutboxEvent.status
                )
            )
        ).all()
        for status in ("PENDING", "PROCESSING", "PROCESSED", "FAILED"):
            workflow_outbox_events_by_status.labels(status=status).set(0)
        for status, count in outbox_counts:
            workflow_outbox_events_by_status.labels(status=str(status)).set(count)

        oldest_pending = await session.execute(
            text(
                "SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(created_at)), 0) "
                "FROM workflow_outbox_events WHERE status = 'PENDING' "
                "AND available_at <= NOW()"
            )
        )
        workflow_outbox_oldest_pending_seconds.set(float(oldest_pending.scalar_one()))

        connections = (
            await session.execute(
                text(
                    "SELECT COALESCE(state, 'unknown'), COUNT(*) "
                    "FROM pg_stat_activity WHERE datname = current_database() "
                    "GROUP BY state"
                )
            )
        ).all()
        for state in (
            "active",
            "idle",
            "idle in transaction",
            "idle in transaction (aborted)",
            "fastpath function call",
            "disabled",
            "unknown",
        ):
            database_connections.labels(state=state).set(0)
        for state, count in connections:
            database_connections.labels(state=str(state)).set(count)

        database_row = (
            await session.execute(
                text(
                    "SELECT pg_database_size(current_database()), "
                    "(SELECT setting::bigint FROM pg_settings WHERE name = 'max_connections'), "
                    "xact_commit, xact_rollback, deadlocks "
                    "FROM pg_stat_database WHERE datname = current_database()"
                )
            )
        ).one()
        size_bytes, max_connections, committed, rolled_back, deadlocks = database_row
        database_size_bytes.set(size_bytes)
        database_max_connections.set(max_connections)
        database_transactions.labels(outcome="committed").set(committed)
        database_transactions.labels(outcome="rolled_back").set(rolled_back)
        database_deadlocks.set(deadlocks)


async def _refresh_redis_state() -> None:
    redis = await get_redis_client()
    redis_queue_capacity.set(TaskQueue.MAX_QUEUE_DEPTH)
    redis_queue_items.labels(queue="ready").set(await redis.llen("blogify:tasks"))
    redis_queue_items.labels(queue="processing").set(await redis.zcard("blogify:processing"))
    worker_count = 0
    active_jobs = 0
    capacity = 0
    async for key in redis.scan_iter(match="blogify:worker:*"):
        worker_count += 1
        value = await redis.get(key)
        if not value:
            continue
        try:
            heartbeat = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        active_jobs += int(heartbeat.get("active_jobs", 0))
        capacity += int(heartbeat.get("capacity", 0))
    workers_active.set(worker_count)
    workers_active_jobs.set(active_jobs)
    workers_capacity.set(capacity)


def update_database_pool_metrics(process_name: str) -> None:
    """Publish local SQLAlchemy pool state with a bounded process label."""
    pool = engine.sync_engine.pool
    database_pool_connections.labels(process=process_name, state="size").set(pool.size())
    database_pool_connections.labels(process=process_name, state="checked_out").set(
        pool.checkedout()
    )
    database_pool_connections.labels(process=process_name, state="overflow").set(
        pool.overflow()
    )


async def runtime_metrics_poller(
    process_name: str,
    *,
    include_shared_state: bool,
    interval_seconds: int = 15,
) -> None:
    """Keep runtime gauges fresh without putting database/Redis work on scrapes."""
    while True:
        try:
            refresh_ok = await refresh_runtime_metrics(
                process_name,
                include_shared_state=include_shared_state,
            )
            if refresh_ok is False:
                runtime_metrics_refresh_errors_total.labels(process=process_name).inc()
            else:
                runtime_metrics_refresh_success_timestamp_seconds.labels(
                    process=process_name
                ).set(time.time())
        except asyncio.CancelledError:
            raise
        except Exception:
            runtime_metrics_refresh_errors_total.labels(process=process_name).inc()
            logger.warning("runtime_metrics_refresh_failed", process=process_name, exc_info=True)
        await asyncio.sleep(interval_seconds)


async def cancel_metrics_task(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
