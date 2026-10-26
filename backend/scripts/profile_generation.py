#!/usr/bin/env python3
"""Report end-to-end and per-agent timings for one or more blog sessions.

Run from ``backend/`` after the workflow has completed, for example:

    .venv/bin/python scripts/profile_generation.py --session-ids 101 102 103

The report is read-only. Stage durations are recorded by the agent timing
callbacks and persisted in ``agent_runs.latency_ms`` by the worker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from src.core.database import AsyncSessionFactory, engine  # noqa: E402
from src.models.orm_models import (  # noqa: E402
    AgentRun,
    BlogReviewEvent,
    BlogSession,
    SessionLease,
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return ordered[index]


def _summary(values: list[int]) -> dict[str, int | float | None]:
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values)) if values else None,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values) if values else None,
    }


async def _profile_session(session_id: int) -> dict[str, Any]:
    async with AsyncSessionFactory() as db:
        blog = await db.get(BlogSession, session_id)
        if blog is None:
            return {"session_id": session_id, "error": "session not found"}

        runs_result = await db.execute(
            select(AgentRun)
            .where(AgentRun.blog_session_id == session_id)
            .order_by(AgentRun.started_at, AgentRun.id)
        )
        runs = list(runs_result.scalars().all())
        leases_result = await db.execute(
            select(SessionLease)
            .where(SessionLease.blog_session_id == session_id)
            .order_by(SessionLease.started_at, SessionLease.id)
        )
        leases = list(leases_result.scalars().all())
        reviews_result = await db.execute(
            select(BlogReviewEvent)
            .where(BlogReviewEvent.blog_session_id == session_id)
            .order_by(BlogReviewEvent.created_at, BlogReviewEvent.id)
        )
        review_events = list(reviews_result.scalars().all())

    now = datetime.now(timezone.utc)
    created_at = _as_utc(blog.created_at)
    completed_at = _as_utc(blog.completed_at) if blog.completed_at else None
    wall_end = completed_at or now
    first_lease = _as_utc(leases[0].started_at) if leases else None
    queue_wait_ms = (
        max(0, round((first_lease - created_at).total_seconds() * 1000))
        if first_lease
        else None
    )
    worker_ms = sum(
        max(
            0,
            round(
                (
                    (_as_utc(lease.ended_at) if lease.ended_at else now)
                    - _as_utc(lease.started_at)
                ).total_seconds()
                * 1000
            ),
        )
        for lease in leases
    )
    wall_time_ms = max(0, round((wall_end - created_at).total_seconds() * 1000))
    outside_worker_ms = max(0, wall_time_ms - worker_ms - (queue_wait_ms or 0))

    stages = [
        {
            "stage": run.stage_name,
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "duration_ms": run.latency_ms,
            "tokens": run.total_tokens,
            "started_at": _as_utc(run.started_at).isoformat(),
            "completed_at": _as_utc(run.completed_at).isoformat()
            if run.completed_at
            else None,
        }
        for run in runs
    ]
    measured_stages = [stage for stage in stages if stage["duration_ms"] is not None]
    missing_timing_stages = [
        stage["stage"] for stage in stages if stage["duration_ms"] is None
    ]
    slowest_stage = max(
        measured_stages, key=lambda stage: stage["duration_ms"], default=None
    )

    return {
        "session_id": session_id,
        "topic": blog.topic,
        "status": blog.status.value if hasattr(blog.status, "value") else blog.status,
        "created_at": created_at.isoformat(),
        "completed_at": completed_at.isoformat() if completed_at else None,
        "wall_time_ms": wall_time_ms,
        "queue_wait_ms": queue_wait_ms,
        "worker_lease_time_ms": worker_ms,
        "outside_worker_time_ms": outside_worker_ms,
        "human_review_events": [
            {"action": event.action, "created_at": _as_utc(event.created_at).isoformat()}
            for event in review_events
        ],
        "stages": stages,
        "slowest_stage": slowest_stage,
        "stages_missing_timing": missing_timing_stages,
    }


async def _run(session_ids: list[int]) -> dict[str, Any]:
    try:
        profiles = [await _profile_session(session_id) for session_id in session_ids]
    finally:
        await engine.dispose()
    valid_profiles = [profile for profile in profiles if "error" not in profile]
    grouped: dict[str, list[int]] = defaultdict(list)
    for profile in valid_profiles:
        for stage in profile["stages"]:
            duration = stage["duration_ms"]
            if duration is not None:
                grouped[stage["stage"]].append(duration)

    wall_times = [profile["wall_time_ms"] for profile in valid_profiles]
    worker_times = [profile["worker_lease_time_ms"] for profile in valid_profiles]
    outside_times = [profile["outside_worker_time_ms"] for profile in valid_profiles]
    queue_times = [
        profile["queue_wait_ms"]
        for profile in valid_profiles
        if profile["queue_wait_ms"] is not None
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_count": len(valid_profiles),
        "sessions": profiles,
        "aggregate": {
            "wall_time": _summary(wall_times),
            "queue_wait": _summary(queue_times),
            "worker_lease_time": _summary(worker_times),
            "outside_worker_time": _summary(outside_times),
            "stages": {
                stage: _summary(durations) for stage, durations in sorted(grouped.items())
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session-ids",
        type=int,
        nargs="+",
        required=True,
        help="One or more Blogify session IDs to profile",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Also write the complete machine-readable report to this path",
    )
    args = parser.parse_args()

    report = asyncio.run(_run(args.session_ids))
    output = json.dumps(report, indent=2)
    print(output)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output + "\n", encoding="utf-8")
    return 1 if any("error" in profile for profile in report["sessions"]) else 0


if __name__ == "__main__":
    sys.exit(main())
