from __future__ import annotations

import importlib
import hashlib
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.orm_models import ClientMode, ClientStatus, HumanReviewAction
from src.models.repositories.identity_repository import IdentityRepository
from src.services.adapter_auth_service import AdapterAuthError, AdapterAuthService
from src.services.service_client_service import ServiceClientService


class _CaptureAsyncSession:
    def __init__(self) -> None:
        self.added = None

    def add(self, obj):
        self.added = obj

    async def flush(self):
        return None

    async def execute(self, _statement):
        return MagicMock(scalar_one_or_none=lambda: None, scalars=lambda: MagicMock(all=lambda: []))


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


class _RevisionRepo:
    def __init__(self, session_obj, version_obj) -> None:
        self._session_obj = session_obj
        self._version_obj = version_obj
        self._review_repo = AsyncMock()
        self._version_repo = AsyncMock()

    async def get_by_id(self, blog_session_id):
        return self._session_obj

    async def update_status(self, *_args, **_kwargs):
        return None

    async def increment_iteration(self, *_args, **_kwargs):
        return self._session_obj.iteration_count + 1


class _VersionRepo:
    def __init__(self, version_obj) -> None:
        self._version_obj = version_obj

    async def get_by_id(self, *_args, **_kwargs):
        return self._version_obj

    async def mark_approved(self, *_args, **_kwargs):
        return None

    async def mark_rejected(self, *_args, **_kwargs):
        return None

    async def create(self, *_args, **_kwargs):
        return SimpleNamespace(id=9, version_number=2)


class _ReviewRepo:
    async def create(self, **_kwargs):
        return None


class _FakeRedis:
    def __init__(self, current: int) -> None:
        self.current = current

    async def get(self, _key):
        return str(self.current)

    def pipeline(self):
        return self

    def incr(self, _key):
        return self

    def expire(self, _key, _ttl):
        return self

    async def execute(self):
        return None


def _install_google_adk_stubs():
    google = sys.modules.setdefault("google", ModuleType("google"))
    adk = ModuleType("google.adk")
    agents = ModuleType("google.adk.agents")
    events = ModuleType("google.adk.events")
    sessions = ModuleType("google.adk.sessions")
    base_sessions = ModuleType("google.adk.sessions.base_session_service")

    class _Stub:
        pass

    agents.Agent = _Stub
    agents.LoopAgent = _Stub
    agents.SequentialAgent = _Stub
    events.Event = _Stub
    sessions.BaseSessionService = _Stub
    sessions.Session = _Stub
    base_sessions.ListSessionsResponse = _Stub

    adk.agents = agents
    adk.events = events
    adk.sessions = sessions
    google.adk = adk

    return {
        "google.adk": adk,
        "google.adk.agents": agents,
        "google.adk.events": events,
        "google.adk.sessions": sessions,
        "google.adk.sessions.base_session_service": base_sessions,
    }


def _install_pipeline_stub():
    module = ModuleType("src.agents.pipeline_v2")

    class CostInfo:
        def __init__(self, stage="", total_tokens=0, model=None, prompt_tokens=0, completion_tokens=0):
            self.stage = stage
            self.total_tokens = total_tokens
            self.model = model
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens

    class PipelineResult:
        pass

    async def run_pipeline(**_kwargs):
        return PipelineResult()

    async def resume_pipeline(**_kwargs):
        return PipelineResult()

    module.CostInfo = CostInfo
    module.PipelineResult = PipelineResult
    module.run_pipeline = run_pipeline
    module.resume_pipeline = resume_pipeline
    return {"src.agents.pipeline_v2": module}


class TestAdminConfigValidation:
    def test_startup_configuration_rejects_missing_admin_key(self, monkeypatch):
        from src.core import startup

        monkeypatch.setattr(startup.config, "environment", "prod")
        monkeypatch.setattr(startup.config, "cors_origins", ["https://app.blogify.ai"])
        monkeypatch.setattr(startup.config, "worker_heartbeat_interval_seconds", 15)
        monkeypatch.setattr(startup.config, "worker_heartbeat_ttl_seconds", 45)
        monkeypatch.setattr(startup.config, "enable_admin_routes", True)
        monkeypatch.setattr(startup.config, "admin_api_key", None)

        result = startup.runtime_manager.check_configuration()

        assert result.status == "unhealthy"
        assert "ADMIN_API_KEY must be explicitly set when admin routes are enabled" in result.details["issues"]


class TestIdentityRepositoryServiceClientLifecycle:
    @pytest.mark.asyncio
    async def test_create_service_client_hashes_raw_key(self):
        session = _CaptureAsyncSession()
        repo = IdentityRepository(session)

        client = await repo.create_service_client(
            client_key="svc-a",
            name="Service A",
            raw_api_key="plain-secret",
            mode=ClientMode.BLOGIFY_SERVICE,
        )

        assert session.added is client
        assert client.hashed_api_key == hashlib.sha256("plain-secret".encode()).hexdigest()
        assert client.hashed_api_key != "plain-secret"

    @pytest.mark.asyncio
    async def test_service_client_service_returns_raw_key_only_on_create(self):
        repo = AsyncMock()
        repo.create_service_client.return_value = SimpleNamespace(client_key="svc-a")
        service = ServiceClientService(repo)

        with patch.object(service, "generate_api_key", return_value="generated-secret"):
            client, raw_key = await service.create_service_client(
                client_key="svc-a",
                name="Service A",
                mode=ClientMode.BLOGIFY_SERVICE,
            )

        assert client.client_key == "svc-a"
        assert raw_key == "generated-secret"
        repo.create_service_client.assert_awaited_once_with(
            client_key="svc-a",
            name="Service A",
            raw_api_key="generated-secret",
            mode=ClientMode.BLOGIFY_SERVICE,
        )


class TestAdminServiceClientRoutes:
    @pytest.mark.asyncio
    async def test_require_admin_api_key_rejects_invalid_value(self):
        from src.api.routes import admin_service_clients

        with patch.object(admin_service_clients.config, "admin_api_key", "expected"):
            with pytest.raises(Exception) as exc:
                admin_service_clients.require_admin_api_key("wrong")

        assert getattr(exc.value, "status_code", 500) == 401

    @pytest.mark.asyncio
    async def test_create_service_client_returns_generated_key(self):
        from src.api.routes import admin_service_clients

        fake_client = SimpleNamespace(
            client_key="svc-a",
            name="Service A",
            mode=ClientMode.BLOGIFY_SERVICE.value,
            status=ClientStatus.ACTIVE.value,
            created_at=datetime.now(timezone.utc),
            rotated_at=None,
        )

        with (
            patch.object(admin_service_clients.config, "admin_api_key", "expected"),
            patch.object(admin_service_clients.db_repository, "async_session", return_value=_AsyncSessionContext()),
            patch.object(admin_service_clients.IdentityRepository, "get_service_client_by_key", new=AsyncMock(return_value=None)),
            patch.object(
                admin_service_clients.ServiceClientService,
                "create_service_client",
                new=AsyncMock(return_value=(fake_client, "raw-key")),
            ),
        ):
            response = await admin_service_clients.create_service_client(
                admin_service_clients.CreateServiceClientRequest(
                    client_key="svc-a",
                    name="Service A",
                    mode=ClientMode.BLOGIFY_SERVICE,
                ),
                x_admin_api_key="expected",
            )

        assert response.api_key == "raw-key"
        assert response.client_key == "svc-a"

    @pytest.mark.asyncio
    async def test_rotate_service_client_returns_new_generated_key(self):
        from src.api.routes import admin_service_clients

        fake_client = SimpleNamespace(
            client_key="svc-a",
            name="Service A",
            mode=ClientMode.BLOGIFY_SERVICE.value,
            status=ClientStatus.ACTIVE.value,
            created_at=datetime.now(timezone.utc),
            rotated_at=None,
        )

        with (
            patch.object(admin_service_clients.config, "admin_api_key", "expected"),
            patch.object(admin_service_clients.db_repository, "async_session", return_value=_AsyncSessionContext()),
            patch.object(
                admin_service_clients.ServiceClientService,
                "rotate_service_client_api_key",
                new=AsyncMock(return_value=(fake_client, "rotated-key")),
            ),
        ):
            response = await admin_service_clients.rotate_service_client(
                "svc-a",
                x_admin_api_key="expected",
            )

        assert response.api_key == "rotated-key"
        assert response.client_key == "svc-a"


class TestOperatorValidationState:
    @pytest.mark.asyncio
    async def test_suspend_then_activate_changes_validation_result(self):
        repo = AsyncMock()
        repo.get_client_by_hashed_api_key.side_effect = [
            None,
            SimpleNamespace(mode=ClientMode.BLOGIFY_SERVICE.value),
        ]
        auth_service = AdapterAuthService(repo)

        with pytest.raises(AdapterAuthError):
            await auth_service.validate_service_api_key("old-key")

        client = await auth_service.validate_service_api_key("new-key")

        assert client.mode == ClientMode.BLOGIFY_SERVICE.value


class TestObservabilityAssetsAndMetrics:
    def test_compose_and_dashboards_include_tempo_assets(self):
        backend_root = Path(__file__).resolve().parents[2]
        compose = (backend_root / "docker-compose.yml").read_text()
        datasources = (
            backend_root / "grafana/provisioning/datasources/datasources.yaml"
        ).read_text()

        assert "tempo:" in compose
        assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317" in compose
        assert "Tempo" in datasources
        assert (backend_root / "grafana/provisioning/dashboards/dashboards.yaml").exists()
        assert (backend_root / "grafana/provisioning/dashboards/api-overview.json").exists()
        assert (backend_root / "grafana/provisioning/dashboards/pipeline-overview.json").exists()
        assert (backend_root / "grafana/provisioning/dashboards/budget-review.json").exists()

    @pytest.mark.asyncio
    async def test_service_rate_limit_rejection_emits_metric(self):
        module = importlib.import_module("src.guards.rate_limit_guard")

        with (
            patch.object(module, "get_redis_client", return_value=_FakeRedis(current=120)),
            patch.object(module.config, "service_rate_limit_requests_per_minute", 120),
            patch.object(module.rate_limit_rejections_total, "labels", return_value=MagicMock(inc=MagicMock())) as labels,
        ):
            allowed, _message, info = await module.rate_limit_guard.check_service_request_limit("svc-a")

        assert allowed is False
        assert info["retry_after"] == 60
        labels.assert_called_once_with(limit_type="service_request")

    def test_stage_executor_emits_agent_metrics(self):
        cost = SimpleNamespace(stage="draft", total_tokens=42, model="gemini", prompt_tokens=10, completion_tokens=32)
        with patch.dict(sys.modules, {**_install_google_adk_stubs(), **_install_pipeline_stub()}):
            sys.modules.pop("src.workers.stage_executor", None)
            with (
                patch("src.workers.stage_executor.get_model_cost", return_value=0.25),
                patch("src.workers.stage_executor.agent_invocations_total.labels", return_value=MagicMock(inc=MagicMock())) as invocations,
                patch("src.workers.stage_executor.agent_token_usage.labels", return_value=MagicMock(observe=MagicMock())) as tokens,
                patch("src.workers.stage_executor.agent_cost_usd.labels", return_value=MagicMock(observe=MagicMock())) as cost_metric,
            ):
                from src.workers.stage_executor import StageExecutor

                StageExecutor()._emit_agent_metrics([cost])

        invocations.assert_called_once_with(agent_name="draft", success="true")
        tokens.assert_called_once_with(agent_name="draft")
        cost_metric.assert_called_once_with(agent_name="draft")

    @pytest.mark.asyncio
    async def test_revision_service_emits_judge_metrics(self):
        from src.services.revision_service import RevisionService
        from src.models.schemas import HumanReviewRequest

        session_obj = SimpleNamespace(id=1, iteration_count=0, end_user_id=1)
        version_obj = SimpleNamespace(id=2, content_markdown="draft", title="Title", word_count=10, sources_count=1)

        service = RevisionService(
            session_repo=_RevisionRepo(session_obj, version_obj),
            version_repo=_VersionRepo(version_obj),
            review_repo=_ReviewRepo(),
            budget_repo=AsyncMock(),
        )

        with (
            patch("src.services.revision_service.judge_decisions_total.labels", return_value=MagicMock(inc=MagicMock())) as decisions,
            patch("src.services.revision_service.judge_quality_score.observe") as quality,
        ):
            result = await service.process_review(
                blog_session_id=1,
                blog_version_id=2,
                request=HumanReviewRequest(action=HumanReviewAction.APPROVE.value, reviewer_user_id="reviewer@example.com"),
            )

        assert result.new_status == "completed"
        decisions.assert_called_once_with(decision="approved")
        quality.assert_called_once_with(1.0)
