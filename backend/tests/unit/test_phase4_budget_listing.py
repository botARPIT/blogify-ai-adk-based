from __future__ import annotations

import importlib
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.models.schemas import BlogSessionListResponse, ServiceClientBudgetDecision


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


def _import_main_module(*, canonical_routes_enabled: bool = True):
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


class TestBlogListingRoute:
    @pytest.mark.asyncio
    async def test_list_my_blogs_requires_authentication(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            request = Request({"type": "http", "headers": []})

            with pytest.raises(HTTPException) as exc:
                await canonical.list_my_blogs(request)

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_list_my_blogs_returns_authenticated_users_sessions(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            request = Request({"type": "http", "headers": []})
            request.state.user_id = "7"
            request.state.user_email = "user@example.com"
            request.state.user_display_name = "User"
            request.state.token_claims = {}
            request.state.authenticated = True

            response = BlogSessionListResponse(
                items=[],
                total=0,
                limit=20,
                offset=0,
            )

            with (
                patch.object(canonical, "_resolve_standalone_budget", new=AsyncMock(return_value=(5, 11))),
                patch.object(canonical, "_list_blog_sessions", new=AsyncMock(return_value=response)) as list_sessions,
            ):
                result = await canonical.list_my_blogs(request, limit=20, offset=0, status="completed")

        assert result is response
        list_sessions.assert_awaited_once_with(
            end_user_id=11,
            tenant_id=5,
            limit=20,
            offset=0,
            status_filter="completed",
        )


class TestServiceClientBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_service_generate_blog_blocks_exhausted_service_client(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            http_request = Request({"type": "http", "headers": []})
            payload = canonical.ServiceGenerateBlogRequest(
                topic="A sufficiently long topic for generation",
                audience="developers",
                tone="formal",
                tenant_id="tenant-1",
                end_user_id="user-1",
                request_id="req-1",
            )

            decision = ServiceClientBudgetDecision(
                allowed=False,
                reason="Service client's daily AI budget is exhausted",
                daily_spent_usd=3.0,
                daily_limit_usd=3.0,
                reset_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
            )

            with (
                patch.object(canonical, "require_internal_service_client", new=AsyncMock()),
                patch.object(
                    canonical,
                    "_resolve_service_identity",
                    new=AsyncMock(
                        return_value=SimpleNamespace(
                            service_client_id=9,
                            tenant_id=5,
                            end_user_id=11,
                            external_user_id="user-1",
                        )
                    ),
                ),
                patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext()),
                patch.object(canonical.ServiceClientBudgetService, "preflight", new=AsyncMock(return_value=decision)),
            ):
                with pytest.raises(HTTPException) as exc:
                    await canonical.service_generate_blog(
                        payload,
                        http_request,
                        x_internal_api_key="valid-key",
                    )

        assert exc.value.status_code == 402
        assert exc.value.detail["reset_at"] == "2026-03-27T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_service_client_budget_service_blocks_when_limit_exhausted(self):
        from src.services.service_client_budget_service import ServiceClientBudgetService

        repo = AsyncMock()
        repo.get_policy.return_value = SimpleNamespace(
            daily_budget_limit_usd=2.0,
            is_active=True,
        )
        repo.get_daily_spent_usd.return_value = 2.5

        service = ServiceClientBudgetService(repo)
        decision = await service.preflight(7)

        assert decision.allowed is False
        assert decision.daily_limit_usd == 2.0
        assert decision.reset_at is not None


class TestAdminBudgetRoutes:
    @pytest.mark.asyncio
    async def test_update_service_client_budget_returns_budget_state(self):
        from src.api.routes import admin_service_clients

        budget_state = SimpleNamespace(
            daily_budget_limit_usd=5.0,
            budget_window="daily",
            currently_exhausted=False,
            reset_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
            daily_spent_usd=1.25,
        )

        with (
            patch.object(admin_service_clients.config, "admin_api_key", "expected"),
            patch.object(admin_service_clients.db_repository, "async_session", return_value=_AsyncSessionContext()),
            patch.object(
                admin_service_clients.IdentityRepository,
                "get_service_client_by_key",
                new=AsyncMock(return_value=SimpleNamespace(id=9)),
            ),
            patch.object(admin_service_clients.ServiceClientBudgetService, "update_policy", new=AsyncMock()),
            patch.object(
                admin_service_clients.ServiceClientBudgetService,
                "get_state",
                new=AsyncMock(return_value=budget_state),
            ),
        ):
            response = await admin_service_clients.update_service_client_budget(
                "svc-a",
                admin_service_clients.UpdateServiceClientBudgetRequest(
                    daily_budget_limit_usd=5.0
                ),
                x_admin_api_key="expected",
            )

        assert response.daily_budget_limit_usd == 5.0
        assert response.daily_spent_usd == 1.25


class TestLoggingHardening:
    def test_mask_sensitive_values_masks_secrets_and_database_credentials(self):
        from src.config import logging_config

        event = {
            "message": "startup",
            "database_url": "postgresql://user:pass@db.example.com/blogify",
            "admin_api_key": "super-secret",
            "nested": {"jwt_secret_key": "jwt-secret"},
        }

        masked = logging_config._mask_sensitive_values(None, None, event)

        assert masked["database_url"] == "***"
        assert masked["admin_api_key"] == "***"
        assert masked["nested"]["jwt_secret_key"] == "***"

    def test_startup_configuration_rejects_non_json_log_format_in_production(self, monkeypatch):
        from src.core import startup

        monkeypatch.setattr(startup.config, "environment", "prod")
        monkeypatch.setattr(startup.config, "cors_origins", ["https://app.blogify.ai"])
        monkeypatch.setattr(startup.config, "worker_heartbeat_interval_seconds", 15)
        monkeypatch.setattr(startup.config, "worker_heartbeat_ttl_seconds", 45)
        monkeypatch.setattr(startup.config, "log_format", "console")
        monkeypatch.setattr(startup.config, "admin_api_key", "expected")

        result = startup.runtime_manager.check_configuration()

        assert result.status == "unhealthy"
        assert "log_format must be json in stage and production" in result.details["issues"]


class TestPhase4Docs:
    def test_architecture_doc_mentions_service_client_budget_policy(self):
        from pathlib import Path

        doc = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE-blogify.md"
        content = doc.read_text()

        assert "service_client_budget_policies" in content
        assert "GET /api/v1/blogs" in content
