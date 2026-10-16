"""Two end-to-end API-to-worker checks using disposable PostgreSQL and Redis."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.e2e

OUTLINE = {
    "title": "Reliable distributed systems",
    "sections": [
        {"id": "intro", "heading": "Introduction", "goal": "Set context", "target_words": 100},
        {"id": "design", "heading": "Design", "goal": "Explain the design", "target_words": 120},
        {"id": "tradeoffs", "heading": "Tradeoffs", "goal": "Discuss tradeoffs", "target_words": 100},
    ],
    "estimated_total_words": 500,
}


async def _generate(e2e):
    return await e2e.client.post(
        "/api/v1/blogs/generate",
        json={
            "topic": "Distributed systems",
            "audience": "backend engineers",
            "tone": "technical",
        },
    )


async def test_api_persists_generation_and_dispatches_outbox_job(e2e):
    from src.models.orm_models import BlogSession, BlogVersion, WorkflowOutboxEvent

    response = await _generate(e2e)
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    async with e2e.sessions() as db:
        session = await db.get(BlogSession, session_id)
        version = await db.scalar(
            select(BlogVersion).where(BlogVersion.blog_session_id == session_id)
        )
        event = await db.scalar(
            select(WorkflowOutboxEvent).where(
                WorkflowOutboxEvent.aggregate_id == session_id
            )
        )
        assert session.status == "QUEUED"
        assert session.job_phase == "fresh_generation"
        assert version.version_number == 1
        assert event.event_type == "blog.generate"
        assert event.dispatched_at is not None

    queued = await e2e.redis.rpop(e2e.queue_key)
    assert queued is not None
    assert json.loads(queued)["session_id"] == session_id


async def test_worker_claims_outbox_job_and_persists_outline_review_checkpoint(e2e, monkeypatch):
    from src.agents.pipeline import PipelineResult
    from src.core.task_queue import BlogJob
    from src.models.orm_models import BlogSession, WorkflowOutboxEvent
    from src.workers.blog_worker import BlogWorker

    response = await _generate(e2e)
    session_id = response.json()["session_id"]
    queued = await e2e.redis.rpop(e2e.queue_key)
    assert queued is not None
    job = BlogJob(**json.loads(queued))

    async def scripted_pipeline(**kwargs):
        assert kwargs["topic"] == "Distributed systems"
        return PipelineResult(session_id=job.adk_session_id, outline=OUTLINE)

    async def no_delay():
        return None

    monkeypatch.setattr("src.workers.executor.run_pipeline", scripted_pipeline)
    monkeypatch.setattr("src.workers.executor.agent_delay", no_delay)
    await BlogWorker()._process_job(job)

    async with e2e.sessions() as db:
        session = await db.get(BlogSession, session_id)
        event = await db.scalar(
            select(WorkflowOutboxEvent).where(
                WorkflowOutboxEvent.aggregate_id == session_id
            )
        )
        assert session.status == "AWAITING_OUTLINE_REVIEW"
        assert session.outline_data == OUTLINE
        assert event.status == "PROCESSED"
