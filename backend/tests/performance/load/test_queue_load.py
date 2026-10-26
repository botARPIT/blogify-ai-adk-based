"""Opt-in Redis transport stress test using isolated temporary keys."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import statistics
import time
import uuid

import pytest

pytestmark = [pytest.mark.slow]


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * quantile))]


@pytest.mark.asyncio
async def test_redis_queue_stress_no_loss_or_duplicate(monkeypatch):
    if os.getenv("BLOGIFY_RUN_REDIS_STRESS") != "1":
        pytest.skip("set BLOGIFY_RUN_REDIS_STRESS=1 to run against a dedicated Redis instance")

    from redis.asyncio import Redis

    import src.core.task_queue as queue_module

    count = int(os.getenv("BLOGIFY_STRESS_MESSAGES", "5000"))
    if count < 1:
        pytest.fail("BLOGIFY_STRESS_MESSAGES must be positive")

    prefix = f"blogify:stress:{uuid.uuid4().hex}"
    redis_url = os.getenv("BLOGIFY_STRESS_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    client = Redis.from_url(redis_url, decode_responses=True, max_connections=64)
    queue = queue_module.TaskQueue()
    queue.QUEUE_KEY = f"{prefix}:queue"
    queue.PROCESSING_KEY = f"{prefix}:processing"
    queue.NOTIFY_CHANNEL = f"{prefix}:notify"

    async def get_client():
        return client

    monkeypatch.setattr(queue_module, "get_redis_client", get_client)
    enqueue_latencies: list[float] = []
    dequeue_latencies: list[float] = []
    producer_limit = asyncio.Semaphore(32)
    try:
        await client.ping()
        jobs = [
            queue_module.BlogJob(
                session_id=i + 1,
                user_id=1,
                adk_session_id=f"stress-{i + 1}",
                topic="synthetic queue benchmark",
                audience="benchmark client",
                tone="professional",
                phase="fresh_generation",
                outbox_event_id=i + 1,
            )
            for i in range(count)
        ]

        async def enqueue(job):
            async with producer_limit:
                started = time.perf_counter()
                await queue.enqueue(job)
                enqueue_latencies.append(time.perf_counter() - started)

        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
            started = time.perf_counter()
            await asyncio.gather(*(enqueue(job) for job in jobs))
            enqueue_elapsed = time.perf_counter() - started

            received: list[int] = []
            receive_lock = asyncio.Lock()

            async def consume():
                while True:
                    async with receive_lock:
                        if len(received) >= count:
                            return
                    started_at = time.perf_counter()
                    item = await queue.dequeue()
                    if item is None:
                        await asyncio.sleep(0.001)
                        continue
                    await queue.acknowledge(item)
                    dequeue_latencies.append(time.perf_counter() - started_at)
                    async with receive_lock:
                        received.append(item.session_id)

            await asyncio.gather(*(consume() for _ in range(min(32, count))))
            total_elapsed = time.perf_counter() - started

        assert len(received) == count
        assert len(set(received)) == count
        assert await client.llen(queue.QUEUE_KEY) == 0
        assert await client.zcard(queue.PROCESSING_KEY) == 0

        print(json.dumps({
            "messages": count,
            "enqueue_throughput_per_second": round(count / enqueue_elapsed, 2),
            "end_to_end_throughput_per_second": round(count / total_elapsed, 2),
            "enqueue_ms_p50": round(percentile(enqueue_latencies, 0.50) * 1000, 2),
            "enqueue_ms_p95": round(percentile(enqueue_latencies, 0.95) * 1000, 2),
            "dequeue_ack_ms_p50": round(statistics.median(dequeue_latencies) * 1000, 2),
            "dequeue_ack_ms_p95": round(percentile(dequeue_latencies, 0.95) * 1000, 2),
            "unique_received": len(set(received)),
        }, indent=2))
    finally:
        try:
            await client.delete(queue.QUEUE_KEY, queue.PROCESSING_KEY)
        except Exception:
            pass
        await client.aclose()
