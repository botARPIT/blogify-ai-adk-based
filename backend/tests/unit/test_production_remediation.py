from __future__ import annotations

import importlib
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from fastapi import HTTPException
from starlette.requests import Request

from src.models.orm_models import LedgerResourceType
from src.models.repositories.budget_repository import BudgetRepository
from src.models.schemas import BudgetSnapshot
from src.api.auth import AuthMiddleware
from src.api.middleware import RateLimitHeaderMiddleware
from src.config.env_config import DevelopmentConfig, ProductionConfig, StagingConfig
from src.services.local_auth_service import LocalAuthService


class _DummyResult:
    def scalar_one(self):
        return 0.0


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _DummyResult()


class _AsyncSessionContext:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @asynccontextmanager
    async def begin(self):
        yield MagicMock()


def _import_main_module(*, canonical_routes_enabled: bool = False):
    sys.modules.pop("src.api.main", None)
    with patch("src.config.env_config.config.enable_canonical_routes", canonical_routes_enabled):
        return importlib.import_module("src.api.main")


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


class TestLocalAuthHardening:
    def test_production_secret_validation_fails_without_secret(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("LOCAL_AUTH_SECRET", raising=False)

        service = LocalAuthService()

        assert service.is_production_secret_invalid() is True
        assert service.is_default_secret_in_use() is False

    def test_startup_configuration_rejects_missing_production_secret(self, monkeypatch):
        from src.core import startup

        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("LOCAL_AUTH_SECRET", raising=False)
        monkeypatch.setattr(startup.config, "environment", "prod")
        monkeypatch.setattr(startup.config, "cors_origins", ["https://app.blogify.ai"])
        monkeypatch.setattr(startup.config, "worker_heartbeat_interval_seconds", 15)
        monkeypatch.setattr(startup.config, "worker_heartbeat_ttl_seconds", 45)

        result = startup.runtime_manager.check_configuration()

        assert result.status == "unhealthy"
        assert "JWT_SECRET_KEY must be explicitly set in production" in result.details["issues"]

    @pytest.mark.asyncio
    async def test_seed_user_is_skipped_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("JWT_SECRET_KEY", "prod-secret")

        auth_repo = AsyncMock()

        await LocalAuthService().ensure_seed_user(auth_repo)

        auth_repo.count_all.assert_not_called()
        auth_repo.create.assert_not_called()


class TestBudgetAccounting:
    @pytest.mark.asyncio
    async def test_daily_spent_query_subtracts_release_entries(self):
        session = _CaptureSession()
        repo = BudgetRepository(session)

        await repo.get_daily_spent(
            end_user_id=42,
            resource_type=LedgerResourceType.USD,
            date_utc=datetime.now(timezone.utc),
        )

        compiled = str(
            session.statement.compile(compile_kwargs={"literal_binds": True})
        ).lower()

        assert "case" in compiled
        assert "release" in compiled
        assert "-budget_ledger_entries.quantity" in compiled


class TestInternalRouteValidation:
    @pytest.mark.asyncio
    async def test_internal_session_route_rejects_invalid_keys(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            request = Request({"type": "http", "method": "GET", "path": "/internal/ai/blogs/123", "headers": []})

            with patch.object(
                canonical,
                "require_internal_service_client",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=401, detail="Invalid or inactive API key")
                ),
            ) as validate_key:
                with pytest.raises(HTTPException) as exc:
                    await canonical.service_get_session("123", request, x_internal_api_key="bad-key")

        validate_key.assert_awaited_once_with(request, "bad-key")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_internal_service_client_helper_rejects_rate_limited_requests(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            request = Request({"type": "http", "headers": []})

            with (
                patch("src.api.routes.canonical.db_repository.async_session", return_value=_AsyncSessionContext()),
                patch(
                    "src.api.routes.canonical.AdapterAuthService.validate_service_api_key",
                    new=AsyncMock(return_value=SimpleNamespace(client_key="svc-client")),
                ),
                patch(
                    "src.api.routes.canonical.rate_limit_guard.check_service_request_limit",
                    new=AsyncMock(
                        return_value=(
                            False,
                            "Service request limit exceeded. Limit: 120/minute",
                            {"limit": 120, "remaining": 0, "reset": 123, "retry_after": 60},
                        )
                    ),
                ),
            ):
                with pytest.raises(HTTPException) as exc:
                    await canonical.require_internal_service_client(request, "valid-key")

        assert exc.value.status_code == 429
        assert request.state.rate_limit_info["limit"] == 120

    @pytest.mark.asyncio
    async def test_internal_service_client_helper_sets_rate_limit_info(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            request = Request({"type": "http", "headers": []})

            with (
                patch("src.api.routes.canonical.db_repository.async_session", return_value=_AsyncSessionContext()),
                patch(
                    "src.api.routes.canonical.AdapterAuthService.validate_service_api_key",
                    new=AsyncMock(return_value=SimpleNamespace(client_key="svc-client")),
                ),
                patch(
                    "src.api.routes.canonical.rate_limit_guard.check_service_request_limit",
                    new=AsyncMock(
                        return_value=(True, "", {"limit": 120, "remaining": 119, "reset": 123})
                    ),
                ),
            ):
                service_client = await canonical.require_internal_service_client(request, "valid-key")

        assert service_client.client_key == "svc-client"
        assert request.state.rate_limit_info["remaining"] == 119


class TestAuthMiddlewareEnforcement:
    @pytest.mark.asyncio
    async def test_auth_middleware_allows_public_auth_routes(self):
        middleware = AuthMiddleware(app=MagicMock(), required=True)
        request = Request({"type": "http", "method": "GET", "path": "/api/v1/auth/me", "headers": []})
        response = Response("ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_middleware_rejects_protected_route_without_auth(self):
        middleware = AuthMiddleware(app=MagicMock(), required=True)
        request = Request({"type": "http", "method": "GET", "path": "/api/v1/costs", "headers": []})
        call_next = AsyncMock(return_value=Response("ok"))

        with pytest.raises(HTTPException) as exc:
            await middleware.dispatch(request, call_next)

        assert exc.value.status_code == 401
        call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_middleware_bypasses_internal_routes(self):
        middleware = AuthMiddleware(app=MagicMock(), required=True)
        request = Request({"type": "http", "method": "GET", "path": "/internal/ai/blogs/123", "headers": []})
        response = Response("ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()


class TestRateLimitHeaders:
    @pytest.mark.asyncio
    async def test_rate_limit_header_middleware_uses_request_state(self):
        middleware = RateLimitHeaderMiddleware(app=MagicMock())
        request = Request({"type": "http", "method": "GET", "path": "/internal/ai/blogs/123", "headers": []})
        request.state.rate_limit_info = {
            "limit": 120,
            "remaining": 119,
            "reset": 123,
            "retry_after": 60,
        }
        response = Response("ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result.headers["X-RateLimit-Limit"] == "120"
        assert result.headers["X-RateLimit-Remaining"] == "119"
        assert result.headers["X-RateLimit-Reset"] == "123"


class TestMonitoringRoutes:
    @pytest.mark.asyncio
    async def test_cost_summary_ignores_query_user_id_and_uses_authenticated_user(self):
        main = _import_main_module()
        snapshot = BudgetSnapshot(
            end_user_id=11,
            tenant_id=5,
            daily_spent_usd=0.4,
            daily_spent_tokens=1200,
            daily_limit_usd=2.0,
            daily_limit_tokens=5000,
            active_sessions=0,
            max_concurrent_sessions=2,
            remaining_revision_iterations=1,
        )
        request = Request({"type": "http", "headers": []})
        request.state.user_id = "7"
        request.state.user_email = "user@example.com"
        request.state.user_display_name = "User"
        request.state.token_claims = {}
        request.state.authenticated = True

        with patch.dict(sys.modules, _install_google_adk_stubs()):
            with (
                patch("src.api.routes.canonical._resolve_standalone_budget", new=AsyncMock(return_value=(5, 11))),
                patch.object(main.db_repository, "async_session", return_value=_AsyncSessionContext()),
                patch.object(main.BudgetService, "get_snapshot", new=AsyncMock(return_value=snapshot)),
            ):
                response = await main.get_cost_summary(request)

        assert response["user_id"] == "7"
        assert response["daily_cost_usd"] == 0.4
        assert "requested_user_id" not in response

    @pytest.mark.asyncio
    async def test_cost_summary_requires_authentication(self):
        main = _import_main_module()
        request = Request({"type": "http", "headers": []})

        with pytest.raises(HTTPException) as exc:
            await main.get_cost_summary(request)

        assert exc.value.status_code == 401

    def test_cost_summary_signature_no_longer_accepts_user_id(self):
        import inspect

        main = _import_main_module()
        signature = inspect.signature(main.get_cost_summary)

        assert list(signature.parameters) == ["request"]

    @pytest.mark.asyncio
    async def test_system_info_is_hidden_in_production(self):
        main = _import_main_module()

        with patch.object(main.config, "environment", "prod"):
            with pytest.raises(HTTPException) as exc:
                await main.system_info()

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_metrics_stays_public_when_configured_public(self):
        main = _import_main_module()
        request = Request({"type": "http", "headers": []})

        with (
            patch.object(main.config, "enable_metrics", True),
            patch.object(main.config, "metrics_public", True),
            patch.object(main, "metrics_endpoint", new=AsyncMock(return_value={"metrics": "ok"})),
        ):
            response = await main.metrics(request)

        assert response == {"metrics": "ok"}

    @pytest.mark.asyncio
    async def test_metrics_requires_internal_api_key_when_not_public(self):
        main = _import_main_module()
        request = Request({"type": "http", "headers": []})
        canonical_stub = ModuleType("src.api.routes.canonical")
        canonical_stub.require_internal_service_client = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Invalid or inactive API key")
        )

        with patch.dict(sys.modules, {"src.api.routes.canonical": canonical_stub}):
            with (
                patch.object(main.config, "enable_metrics", True),
                patch.object(main.config, "metrics_public", False),
            ):
                with pytest.raises(HTTPException) as exc:
                    await main.metrics(request, x_internal_api_key="bad-key")

        assert exc.value.status_code == 401


class TestConfigDefaults:
    def test_canonical_routes_are_enabled_by_default(self):
        assert DevelopmentConfig.model_fields["enable_canonical_routes"].default is True
        assert StagingConfig.model_fields["enable_canonical_routes"].default is True
        assert ProductionConfig.model_fields["enable_canonical_routes"].default is True

    def test_metrics_are_private_by_default_outside_dev(self):
        assert DevelopmentConfig.model_fields["metrics_public"].default is True
        assert StagingConfig.model_fields["metrics_public"].default is False
        assert ProductionConfig.model_fields["metrics_public"].default is False


class TestTracingWiring:
    @pytest.mark.asyncio
    async def test_lifespan_instruments_fastapi_app(self):
        main = _import_main_module()

        with (
            patch.object(main.runtime_manager, "initialize_api", new=AsyncMock()),
            patch.object(main.runtime_manager, "shutdown_api", new=AsyncMock()),
            patch.object(main.db_repository, "async_session", return_value=_AsyncSessionContext()),
            patch.object(main.LocalAuthService, "ensure_seed_user", new=AsyncMock()),
            patch.object(main, "init_tracing") as init_tracing,
            patch.object(main, "instrument_app") as instrument_app,
            patch.object(main.asyncio, "get_event_loop", return_value=SimpleNamespace(add_signal_handler=MagicMock())),
        ):
            async with main.lifespan(main.app):
                pass

        init_tracing.assert_called_once_with(service_name="blogify-api")
        instrument_app.assert_called_once_with(main.app)

    def test_engine_creation_instruments_database(self, monkeypatch):
        from src.models import repository

        monkeypatch.setattr(repository, "_engine", None)
        monkeypatch.setattr(repository, "_async_session_factory", None)
        monkeypatch.setattr(repository, "_database_instrumented", False)

        fake_engine = object()
        with (
            patch.object(repository, "create_async_engine", return_value=fake_engine),
            patch.object(repository, "instrument_database") as instrument_database,
        ):
            engine = repository.get_engine()

        assert engine is fake_engine
        instrument_database.assert_called_once_with(fake_engine)
