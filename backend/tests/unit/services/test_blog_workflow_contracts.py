"""Focused unit tests for API-side lifecycle decisions and dispatch contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.orm_models import BlogSessionStatus
from src.services.blog_service import BlogService
from src.services.exceptions import SessionTerminalError

pytestmark = pytest.mark.unit

OUTLINE = {
    "title": "Reliable systems",
    "sections": [
        {"id": "intro", "heading": "Intro", "goal": "Set context", "target_words": 100},
        {"id": "design", "heading": "Design", "goal": "Explain design", "target_words": 120},
        {"id": "tradeoffs", "heading": "Tradeoffs", "goal": "Discuss tradeoffs", "target_words": 100},
    ],
    "estimated_total_words": 500,
}


def service(*, session=None, existing=None, active_count=0, event=None, version=None):
    db_session = session or AsyncMock()
    session_repo = AsyncMock()
    session_repo.session = db_session
    session_repo.get_by_idempotency_key.return_value = existing
    session_repo.count_active_for_user.return_value = active_count
    session_repo.create.return_value = SimpleNamespace(
        id=41,
        status="QUEUED",
        user_id=7,
        topic="Distributed systems",
        audience="engineers",
        tone="technical",
        adk_session_id="adk-41",
        current_stage=None,
    )
    version_repo = AsyncMock()
    budget_service = AsyncMock()
    task_queue = AsyncMock()
    redis = AsyncMock()
    redis.set.return_value = True
    sut = BlogService(session_repo, version_repo, budget_service, task_queue, redis)
    sut._quota_repo = AsyncMock()
    sut._quota_repo.consume_daily_slot.return_value = True
    sut._outbox = AsyncMock()
    sut._outbox.get_undispatched_for_aggregate.return_value = event
    sut._outbox.enqueue.return_value = SimpleNamespace(id=9)
    sut._review_events = AsyncMock()
    sut._version_repo = version_repo
    if version is not None:
        version_repo.get_active_for_session.return_value = version
    return sut, session_repo, version_repo, budget_service, task_queue, redis


@pytest.mark.asyncio
async def test_agent_timing_callback_accumulates_repeated_stage_invocations(monkeypatch):
    from src.agents import timing

    ticks = iter([1_000_000, 6_000_000, 10_000_000, 18_000_000])
    monkeypatch.setattr(timing, "perf_counter_ns", lambda: next(ticks))
    before, after = timing.agent_timing_callbacks("writer")
    context = SimpleNamespace(state={})

    await before(context)
    await after(context)
    await before(context)
    await after(context)

    assert context.state[timing.AGENT_TIMINGS_STATE_KEY] == {"writer": 13}


@pytest.mark.asyncio
async def test_get_session_rejects_missing_session():
    sut, repo, *_ = service()
    repo.get_by_id.return_value = None
    with pytest.raises(ValueError, match="Session not found"):
        await sut.get_session(7, 41)


@pytest.mark.asyncio
async def test_get_session_rejects_cross_user_access():
    sut, repo, *_ = service()
    repo.get_by_id.return_value = SimpleNamespace(id=41, user_id=8)
    with pytest.raises(ValueError, match="Access denied"):
        await sut.get_session(7, 41)


@pytest.mark.asyncio
async def test_generation_returns_existing_nonterminal_idempotent_request():
    existing = SimpleNamespace(id=41, status="QUEUED")
    sut, repo, version_repo, budget, queue, redis = service(existing=existing)
    result = await sut.create_generation(
        user_id=7, topic="ignored", audience="engineers", tone="technical", idempotency_key="k"
    )
    assert result is existing
    repo.create.assert_not_awaited()
    version_repo.create_initial_version.assert_not_awaited()
    budget.check_and_reserve.assert_not_awaited()
    sut._outbox.enqueue.assert_not_awaited()
    queue.enqueue.assert_not_awaited()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_rejects_reuse_of_terminal_idempotency_key():
    existing = SimpleNamespace(id=41, status=BlogSessionStatus.COMPLETED.value)
    sut, *_ = service(existing=existing)
    with pytest.raises(SessionTerminalError):
        await sut.create_generation(
            user_id=7, topic="topic", audience="engineers", tone="technical", idempotency_key="k"
        )


@pytest.mark.asyncio
async def test_generation_enforces_one_active_session_per_user():
    sut, repo, *_ = service(active_count=1)
    with pytest.raises(ValueError, match="already has an active generation"):
        await sut.create_generation(user_id=7, topic="topic", audience="engineers", tone="technical")
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_creates_initial_version_and_reserves_budget():
    sut, repo, version_repo, budget, _, _ = service()
    result = await sut.create_generation(
        user_id=7, topic="Distributed systems", audience="engineers", tone="technical"
    )
    assert result.id == 41
    repo.create.assert_awaited_once()
    version_repo.create_initial_version.assert_awaited_once()
    budget.check_and_reserve.assert_awaited_once_with(7, 41)
    kwargs = sut._outbox.enqueue.await_args.kwargs
    assert kwargs["event_type"] == "blog.generate"
    assert kwargs["aggregate_id"] == 41
    assert kwargs["payload"]["job"]["phase"] == "fresh_generation"


@pytest.mark.asyncio
async def test_generation_releases_budget_lock_after_reservation_error():
    sut, _, _, budget, _, redis = service()
    budget.check_and_reserve.side_effect = RuntimeError("db failure")
    with pytest.raises(RuntimeError, match="db failure"):
        await sut.create_generation(user_id=7, topic="topic", audience="engineers", tone="technical")
    redis.delete.assert_awaited_once_with("budget_lock:7")
    sut._outbox.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_fails_fast_when_budget_lock_is_unavailable():
    sut, _, _, budget, _, redis = service()
    redis.set.return_value = False
    with pytest.raises(ValueError, match="Rate limit exceeded"):
        await sut.create_generation(user_id=7, topic="topic", audience="engineers", tone="technical")
    budget.check_and_reserve.assert_not_awaited()
    redis.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_commits_even_when_there_is_no_undispatched_event():
    sut, repo, *_ = service(event=None)
    await sut.commit_and_dispatch(41)
    repo.session.commit.assert_awaited_once()
    sut._task_queue.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_enqueues_job_then_marks_event_dispatched():
    event = SimpleNamespace(id=9, payload={"job": {
        "session_id": 41, "user_id": 7, "adk_session_id": "adk-41",
        "topic": "topic", "audience": "engineers", "tone": "technical",
        "phase": "fresh_generation",
    }})
    sut, repo, *_ = service(event=event)
    await sut.commit_and_dispatch(41)
    sut._task_queue.enqueue.assert_awaited_once()
    queued_job = sut._task_queue.enqueue.await_args.args[0]
    assert queued_job.outbox_event_id == 9
    sut._outbox.mark_dispatched.assert_awaited_once_with(9)
    assert repo.session.commit.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_enqueue_failure_leaves_event_for_reaper():
    event = SimpleNamespace(id=9, payload={"job": {"broken": True}})
    sut, repo, *_ = service(event=event)
    await sut.commit_and_dispatch(41)
    repo.session.commit.assert_awaited_once()
    sut._outbox.mark_dispatched.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_marker_failure_rolls_back_marker_transaction():
    event = SimpleNamespace(id=9, payload={"job": {
        "session_id": 41, "user_id": 7, "adk_session_id": "adk-41",
        "topic": "topic", "audience": "engineers", "tone": "technical",
        "phase": "fresh_generation",
    }})
    sut, repo, *_ = service(event=event)
    sut._outbox.mark_dispatched.side_effect = RuntimeError("marker unavailable")
    await sut.commit_and_dispatch(41)
    repo.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_outline_review_copies_human_feedback_into_snapshot_and_continuation_job():
    session = SimpleNamespace(
        id=41, user_id=7, status="AWAITING_OUTLINE_REVIEW", adk_session_id="adk-41",
        topic="topic", audience="engineers", tone="technical", outline_data=None,
    )
    version = SimpleNamespace(id=3, state_snapshot={"intent_result": {}})
    sut, repo, version_repo, *_ = service(version=version)
    repo.get_by_id_for_update.return_value = session
    feedback = "Add a concrete example."

    result = await sut.submit_outline_review(
        user_id=7, session_id=41, approved_outline=OUTLINE, feedback_text=feedback
    )

    assert result.status == "QUEUED"
    update = version_repo.update_version_state.await_args.kwargs
    assert update["feedback_text"] == feedback
    assert update["state_snapshot"]["outline_feedback"] == feedback
    assert sut._outbox.enqueue.await_args.kwargs["payload"]["job"]["phase"] == "research_phase"
    assert sut._review_events.create.await_args.kwargs["feedback_text"] == feedback


@pytest.mark.asyncio
async def test_outline_review_rejects_session_in_wrong_state():
    session = SimpleNamespace(id=41, user_id=7, status="PROCESSING")
    sut, repo, *_ = service()
    repo.get_by_id_for_update.return_value = session
    with pytest.raises(ValueError, match="not awaiting outline review"):
        await sut.submit_outline_review(user_id=7, session_id=41, approved_outline=OUTLINE)
    sut._outbox.enqueue.assert_not_awaited()
