"""Real API, PostgreSQL, Redis, worker persistence and workflow status metrics.

Only the provider-facing executor is scripted; queue deliveries, ownership
claims, review transitions, transactions and Prometheus updates run normally.
"""

import pytest

from src.core.task_queue import TaskQueue
from src.monitoring.metrics import blog_sessions_by_status, worker_jobs_total
from src.monitoring.runtime_metrics import _refresh_postgres_state
from src.workers.job_attempt_processor import WorkflowAttemptProcessor
from src.workflows.contracts import WorkflowRunResult

OUTLINE = {
    "title": "Observability for background jobs",
    "sections": [
        {"id": str(i), "heading": f"Section {i}", "goal": "Explain the metrics", "target_words": 100}
        for i in range(1, 4)
    ],
    "estimated_total_words": 300,
}


async def create_generation(e2e):
    response = await e2e.client.post("/api/v1/blogs/generate", json={
        "topic": "Observability for background blog generation jobs",
        "audience": "software engineers",
        "tone": "technical",
    })
    assert response.status_code == 202, response.text
    return response.json()["session_id"]


async def process_delivery():
    queue = TaskQueue()
    delivery = await queue.dequeue()
    assert delivery is not None
    await WorkflowAttemptProcessor(queue, "e2e-metrics-worker").process(delivery)


async def assert_status(e2e, session_id, expected):
    response = await e2e.client.get(f"/api/v1/blogs/{session_id}/status")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected
    await _refresh_postgres_state()
    assert blog_sessions_by_status.labels(status=expected)._value.get() == 1


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_human_review_lifecycle_and_durable_status_metrics(e2e, monkeypatch):
    async def execute(_self, job):
        if job.phase == "fresh_generation":
            return WorkflowRunResult(
                adk_session_id=job.adk_session_id,
                intent_result={"intent_clear": True}, outline=OUTLINE,
            )
        return WorkflowRunResult(
            adk_session_id=job.adk_session_id,
            outline=OUTLINE,
            draft="# Verified generation",
            final_content="# Verified generation",
            editor_review={"approved": True, "feedback": ""},
        )

    monkeypatch.setattr("src.workers.executor.WorkflowExecutor.execute", execute)
    from src.core.startup import runtime_manager

    assert (await runtime_manager._check_database()).status == "healthy"
    assert runtime_manager.uptime().total_seconds() >= 0
    session_id = await create_generation(e2e)
    before = worker_jobs_total.labels(phase="fresh_generation", outcome="succeeded")._value.get()
    await process_delivery()
    await assert_status(e2e, session_id, "AWAITING_OUTLINE_REVIEW")
    assert worker_jobs_total.labels(phase="fresh_generation", outcome="succeeded")._value.get() == before + 1

    response = await e2e.client.post(f"/api/v1/blogs/{session_id}/outline/review", json={
        "action": "approve", "edited_outline": OUTLINE,
    })
    assert response.status_code == 200, response.text
    await process_delivery()
    await assert_status(e2e, session_id, "AWAITING_FINAL_REVIEW")

    response = await e2e.client.post(f"/api/v1/blogs/{session_id}/final-review", json={"action": "approved"})
    assert response.status_code == 200, response.text
    await assert_status(e2e, session_id, "COMPLETED")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_terminal_generation_failure_updates_state_and_worker_counter(e2e, monkeypatch):
    async def execute(_self, _job):
        raise ValueError("scripted terminal generation failure")

    monkeypatch.setattr("src.workers.executor.WorkflowExecutor.execute", execute)
    session_id = await create_generation(e2e)
    counter = worker_jobs_total.labels(phase="fresh_generation", outcome="failed")
    before = counter._value.get()
    await process_delivery()
    await assert_status(e2e, session_id, "FAILED")
    assert counter._value.get() == before + 1
