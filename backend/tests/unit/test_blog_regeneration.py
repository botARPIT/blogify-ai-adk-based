from __future__ import annotations

import importlib
import json
import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request


class _AsyncSessionContext:
    def __init__(self, session=None) -> None:
        self.session = session or MagicMock()
        self.session.begin = self.begin

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @asynccontextmanager
    async def begin(self):
        yield self.session


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _FakePipeline:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.commands.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self.commands.append(("expire", f"{key}:{seconds}"))

    async def execute(self) -> None:
        return None


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | None] = {}
        self.queue: list[str] = []
        self.tasks: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.setex_calls: list[tuple[str, int, str]] = []
        self.pipeline_obj = _FakePipeline()

    async def get(self, key: str):
        task_id = key.removeprefix("blogify:task:")
        if task_id in self.tasks:
            return json.dumps(self.tasks[task_id])
        return self.values.get(key)

    async def llen(self, key: str) -> int:
        return len(self.queue)

    async def lrange(self, key: str, start: int, end: int):
        return self.queue[start : end + 1]

    async def setex(self, key: str, seconds: int, value: str) -> None:
        self.setex_calls.append((key, seconds, value))
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.deleted.append(key)

    def pipeline(self):
        return self.pipeline_obj


def _request(method: str = "GET") -> Request:
    headers = []
    if method != "GET":
        headers.append((b"x-requested-with", b"XMLHttpRequest"))
    return Request({"type": "http", "method": method, "headers": headers})


def _install_google_adk_stubs():
    google = sys.modules.setdefault("google", ModuleType("google"))
    adk = ModuleType("google.adk")
    events = ModuleType("google.adk.events")
    sessions = ModuleType("google.adk.sessions")
    base_sessions = ModuleType("google.adk.sessions.base_session_service")

    class Event:
        pass

    class Session:
        pass

    class BaseSessionService:
        pass

    class ListSessionsResponse:
        pass

    events.Event = Event
    sessions.BaseSessionService = BaseSessionService
    sessions.Session = Session
    base_sessions.ListSessionsResponse = ListSessionsResponse

    adk.events = events
    adk.sessions = sessions
    google.adk = adk

    return {
        "google.adk": adk,
        "google.adk.events": events,
        "google.adk.sessions": sessions,
        "google.adk.sessions.base_session_service": base_sessions,
    }


def _import_canonical():
    with patch.dict(sys.modules, _install_google_adk_stubs()):
        sys.modules.pop("src.api.routes.canonical", None)
        return importlib.import_module("src.api.routes.canonical")


@pytest.mark.asyncio
async def test_active_session_count_only_counts_processing():
    from src.models.repositories.blog_session_repository import BlogSessionRepository

    db = AsyncMock()
    db.execute.return_value = _ScalarResult(7)

    count = await BlogSessionRepository(db).count_active_for_end_user(11)

    assert count == 7
    statement = db.execute.await_args.args[0]
    compiled = statement.compile()
    assert "status_1" in compiled.params
    assert compiled.params["status_1"] == "processing"


@pytest.mark.asyncio
async def test_queue_lookup_scans_full_queue_and_returns_one_based_position():
    from src.core.task_queue import TaskQueue

    redis = _FakeRedis()
    redis.queue = ["newest", "middle", "oldest"]
    redis.tasks = {
        "newest": {"payload": {"canonical_session_id": 999}},
        "middle": {"payload": {"canonical_session_id": 42}},
        "oldest": {"payload": {"canonical_session_id": 100}},
    }
    queue = TaskQueue()
    queue._get_client = AsyncMock(return_value=redis)

    in_queue, position = await queue.is_job_in_queue(42)

    assert in_queue is True
    assert position == 2


@pytest.mark.asyncio
async def test_queue_status_cache_uses_15_second_ttl_and_invalidates():
    from src.core.task_queue import TaskQueue

    redis = _FakeRedis()
    redis.queue = ["task-1"]
    redis.tasks = {"task-1": {"payload": {"canonical_session_id": 42}}}
    queue = TaskQueue()
    queue._get_client = AsyncMock(return_value=redis)

    data, fresh = await queue.get_cached_queue_status(42)
    await queue.invalidate_queue_status_cache(42)

    assert fresh is True
    assert data["is_in_queue"] is True
    assert data["queue_position"] == 1
    assert redis.setex_calls[0][0] == "queue_status:42"
    assert redis.setex_calls[0][1] == 15
    assert redis.deleted == ["queue_status:42"]


@pytest.mark.asyncio
async def test_regenerate_rate_limit_uses_dedicated_key():
    from src.guards.rate_limit_guard import EnhancedRateLimiter

    redis = _FakeRedis()
    rate_limit_module = importlib.import_module("src.guards.rate_limit_guard")
    with patch.object(rate_limit_module, "get_redis_client", return_value=redis):
        allowed, message = await EnhancedRateLimiter().check_user_regenerate_limit("user-1")

    assert allowed is True
    assert message == ""
    assert ("incr", "rate_limit:user:regenerate:user-1") in redis.pipeline_obj.commands
    assert ("expire", "rate_limit:user:regenerate:user-1:60") in redis.pipeline_obj.commands


def test_stage_to_job_phase_mapping_is_exact_for_required_stages():
    canonical = _import_canonical()

    assert canonical.STAGE_TO_JOB_PHASE["intent"] == "outline_gate"
    assert canonical.STAGE_TO_JOB_PHASE["outline"] == "research_phase"
    assert canonical.STAGE_TO_JOB_PHASE["research"] == "writer_phase"
    assert canonical.STAGE_TO_JOB_PHASE["writer"] == "editor_phase"
    assert canonical.STAGE_TO_JOB_PHASE["editor"] == "final_review"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_status", "owned_by", "is_in_queue", "available", "message"),
    [
        ("completed", None, False, False, None),
        ("queued", "worker-1", False, False, "Worker is processing this blog"),
        ("queued", None, True, False, "Blog will generate shortly"),
        ("queued", None, False, True, "Click to start generation"),
        ("processing", None, False, True, "Session stalled - regenerating"),
    ],
)
async def test_queue_status_response_states(
    session_status,
    owned_by,
    is_in_queue,
    available,
    message,
):
    canonical = _import_canonical()
    user = SimpleNamespace(user_id="user-1", email="user@example.com")
    blog_session = SimpleNamespace(
        id=42,
        end_user_id=11,
        status=session_status,
        current_stage="intent",
        owned_by=owned_by,
        claimed_at=None,
        lease_version=3,
    )
    repo = SimpleNamespace(get_by_id=AsyncMock(return_value=blog_session))

    with (
        patch.object(canonical, "require_authenticated_user", return_value=user),
        patch.object(canonical, "_assert_owned_session", new=AsyncMock()),
        patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext()),
        patch.object(canonical, "BlogSessionRepository", return_value=repo),
        patch.object(
            canonical.task_queue,
            "get_cached_queue_status",
            new=AsyncMock(return_value=({"is_in_queue": is_in_queue, "queue_position": 4}, True)),
        ),
    ):
        response = await canonical.get_queue_status("42", _request())

    assert response.regenerate_available is available
    assert response.regenerate_message == message
    assert response.queue_position == (4 if is_in_queue else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blog_session", "queue_result", "expected_status"),
    [
        (SimpleNamespace(id=42, end_user_id=11, status="completed", owned_by=None, lease_version=1, current_stage="intent"), (False, None), 400),
        (SimpleNamespace(id=42, end_user_id=11, status="queued", owned_by="worker-1", lease_version=1, current_stage="intent"), (False, None), 409),
        (SimpleNamespace(id=42, end_user_id=11, status="queued", owned_by=None, lease_version=2, current_stage="intent"), (False, None), 409),
        (SimpleNamespace(id=42, end_user_id=11, status="queued", owned_by=None, lease_version=1, current_stage="intent"), (True, 1), 409),
    ],
)
async def test_regenerate_rejects_invalid_states(blog_session, queue_result, expected_status):
    canonical = _import_canonical()
    user = SimpleNamespace(user_id="user-1", email="user@example.com")
    identity = SimpleNamespace(
        external_user_id="user-1",
        tenant_id=1,
        end_user_id=11,
    )
    repo = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=blog_session))

    with (
        patch.object(canonical, "require_authenticated_user", return_value=user),
        patch.object(canonical.rate_limit_guard, "check_user_regenerate_limit", new=AsyncMock(return_value=(True, ""))),
        patch.object(canonical, "_resolve_standalone_identity", new=AsyncMock(return_value=identity)),
        patch.object(canonical, "_assert_owned_session", new=AsyncMock()),
        patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext()),
        patch.object(canonical, "BlogSessionRepository", return_value=repo),
        patch.object(canonical.task_queue, "is_job_in_queue", new=AsyncMock(return_value=queue_result)),
    ):
        with pytest.raises(HTTPException) as exc:
            await canonical.regenerate_blog(
                "42",
                canonical.RegenerateRequest(lease_version=1),
                _request("POST"),
            )

    assert exc.value.status_code == expected_status


@pytest.mark.asyncio
async def test_regenerate_rejects_unauthorized_session():
    canonical = _import_canonical()
    user = SimpleNamespace(user_id="user-1", email="user@example.com")
    identity = SimpleNamespace(external_user_id="user-1", tenant_id=1, end_user_id=11)
    blog_session = SimpleNamespace(
        id=42,
        end_user_id=99,
        status="queued",
        owned_by=None,
        lease_version=1,
        current_stage="intent",
    )
    repo = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=blog_session))

    async def reject_ownership(*args, **kwargs):
        raise HTTPException(status_code=403, detail="forbidden")

    with (
        patch.object(canonical, "require_authenticated_user", return_value=user),
        patch.object(canonical.rate_limit_guard, "check_user_regenerate_limit", new=AsyncMock(return_value=(True, ""))),
        patch.object(canonical, "_resolve_standalone_identity", new=AsyncMock(return_value=identity)),
        patch.object(canonical, "_assert_owned_session", new=reject_ownership),
        patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext()),
        patch.object(canonical, "BlogSessionRepository", return_value=repo),
    ):
        with pytest.raises(HTTPException) as exc:
            await canonical.regenerate_blog(
                "42",
                canonical.RegenerateRequest(lease_version=1),
                _request("POST"),
            )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_regenerate_success_enqueues_and_invalidates_cache():
    canonical = _import_canonical()
    user = SimpleNamespace(user_id="user-1", email="user@example.com")
    identity = SimpleNamespace(external_user_id="user-1", tenant_id=1, end_user_id=11)
    blog_session = SimpleNamespace(
        id=42,
        end_user_id=11,
        status="queued",
        current_stage="research",
        owned_by=None,
        claimed_at=None,
        lease_version=1,
        topic="Topic",
        audience="developers",
    )
    repo = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=blog_session))
    session = MagicMock()
    session.begin = _AsyncSessionContext(session).begin
    session.refresh = AsyncMock()

    with (
        patch.object(canonical, "require_authenticated_user", return_value=user),
        patch.object(canonical.rate_limit_guard, "check_user_regenerate_limit", new=AsyncMock(return_value=(True, ""))),
        patch.object(canonical, "_resolve_standalone_identity", new=AsyncMock(return_value=identity)),
        patch.object(canonical, "_assert_owned_session", new=AsyncMock()),
        patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext(session)),
        patch.object(canonical, "BlogSessionRepository", return_value=repo),
        patch.object(canonical.task_queue, "is_job_in_queue", new=AsyncMock(return_value=(False, None))),
        patch.object(canonical.task_queue, "invalidate_queue_status_cache", new=AsyncMock()) as invalidate,
        patch.object(canonical, "enqueue_blog_generation", new=AsyncMock(return_value="task-1")) as enqueue,
    ):
        response = await canonical.regenerate_blog(
            "42",
            canonical.RegenerateRequest(lease_version=1),
            _request("POST"),
        )

    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["job_phase"] == "writer_phase"
    invalidate.assert_awaited_once_with(42)
    assert response.is_in_queue is True
    assert response.regenerate_available is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_phase", "expected_stage"),
    [
        ("research_phase", "research"),
        ("writer_phase", "writer"),
        ("editor_phase", "editor"),
    ],
)
async def test_stage_executor_dispatches_supported_resume_phases(job_phase, expected_stage):
    from src.agents.pipeline import PipelineResult
    from src.workers import stage_executor as stage_executor_module

    executor = stage_executor_module.StageExecutor()
    executor._mark_canonical_processing = AsyncMock()
    executor._finalize_phase_result = AsyncMock(side_effect=lambda _, result: result)
    result = PipelineResult(session_id="42")

    with patch.object(
        stage_executor_module,
        "run_pipeline_from_phase",
        new=AsyncMock(return_value=result),
    ) as run_phase:
        response = await executor.execute_resume_from_job_phase(
            job_phase=job_phase,
            session_id="42",
            topic="Topic",
            audience="developers",
            user_id="user-1",
            canonical_session_id=42,
        )

    executor._mark_canonical_processing.assert_awaited_once_with(
        42,
        current_stage=expected_stage,
    )
    run_phase.assert_awaited_once()
    assert run_phase.await_args.kwargs["phase"] == job_phase
    assert response is result


@pytest.mark.asyncio
async def test_stage_executor_dispatches_final_review_from_state():
    from src.agents.pipeline import PipelineResult
    from src.workers import stage_executor as stage_executor_module

    executor = stage_executor_module.StageExecutor()
    executor._mark_canonical_processing = AsyncMock()
    executor._finalize_phase_result = AsyncMock(side_effect=lambda _, result: result)
    result = PipelineResult(session_id="42")

    with patch.object(
        stage_executor_module,
        "load_pipeline_result_from_state",
        new=AsyncMock(return_value=result),
    ) as load_state:
        response = await executor.execute_resume_from_job_phase(
            job_phase="final_review",
            session_id="42",
            topic="Topic",
            audience="developers",
            user_id="user-1",
            canonical_session_id=42,
        )

    executor._mark_canonical_processing.assert_awaited_once_with(
        42,
        current_stage="final_review",
    )
    load_state.assert_awaited_once()
    assert response is result


@pytest.mark.asyncio
async def test_stage_executor_unknown_phase_falls_back_to_outline_gate():
    from src.agents.pipeline import PipelineResult
    from src.workers import stage_executor as stage_executor_module

    executor = stage_executor_module.StageExecutor()
    result = PipelineResult(session_id="42")
    executor.execute_full_pipeline = AsyncMock(return_value=result)

    response = await executor.execute_resume_from_job_phase(
        job_phase="unknown",
        session_id="42",
        topic="Topic",
        audience="developers",
        user_id="user-1",
        canonical_session_id=42,
    )

    executor.execute_full_pipeline.assert_awaited_once()
    assert response is result
