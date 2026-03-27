from __future__ import annotations

import importlib
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from src.models.schemas import BudgetSnapshot


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


class TestBudgetSnapshotCorrectness:
    @pytest.mark.asyncio
    async def test_budget_snapshot_returns_actual_active_sessions(self):
        from src.services.budget_service import BudgetService

        budget_repo = AsyncMock()
        budget_repo.get_effective_policy.return_value = SimpleNamespace(
            daily_cost_limit_usd=5.0,
            daily_token_limit=10000,
            max_concurrent_sessions=2,
            max_revision_iterations_per_session=3,
        )
        budget_repo.get_daily_spent.side_effect = [1.5, 2500]
        session_repo = AsyncMock()
        session_repo.count_active_for_end_user.return_value = 3

        snapshot = await BudgetService(
            budget_repo=budget_repo,
            session_repo=session_repo,
        ).get_snapshot(tenant_id=5, end_user_id=11)

        assert snapshot.active_sessions == 3
        assert snapshot.remaining_revision_iterations == 3
        session_repo.count_active_for_end_user.assert_awaited_once_with(11)


class TestCanonicalSessionSemantics:
    def test_remaining_revision_iterations_clamps_at_zero(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")

            assert canonical._remaining_revision_iterations(3, 1) == 2
            assert canonical._remaining_revision_iterations(3, 5) == 0

    def test_build_session_state_uses_supplied_remaining_iterations(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")
            session = SimpleNamespace(
                id=1,
                status="awaiting_human_review",
                current_stage="awaiting_review",
                iteration_count=1,
                topic="Topic",
                audience="Audience",
                budget_spent_usd=0.5,
                budget_spent_tokens=123,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                completed_at=None,
            )
            latest_version = SimpleNamespace(version_number=2)

            view = canonical._build_session_state(
                session,
                latest_version,
                remaining_revision_iterations=2,
            )

        assert view.remaining_revision_iterations == 2
        assert view.current_version_number == 2

    @pytest.mark.asyncio
    async def test_list_blog_sessions_keeps_phase4_contract_and_policy_remaining(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            sys.modules.pop("src.api.routes.canonical", None)
            canonical = importlib.import_module("src.api.routes.canonical")

            sessions = [
                SimpleNamespace(
                    id=101,
                    status="processing",
                    current_stage="writer",
                    iteration_count=1,
                    topic="Topic",
                    audience="Audience",
                    budget_spent_usd=0.4,
                    budget_spent_tokens=200,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    completed_at=None,
                )
            ]
            latest_versions = {
                101: SimpleNamespace(version_number=2, title="Latest", word_count=800, sources_count=4)
            }

            fake_session = MagicMock()
            with (
                patch.object(canonical.db_repository, "async_session", return_value=_AsyncSessionContext(fake_session)),
                patch.object(canonical.BlogSessionRepository, "list_for_end_user", new=AsyncMock(return_value=sessions)),
                patch.object(canonical.BlogSessionRepository, "count_for_end_user", new=AsyncMock(return_value=1)),
                patch.object(canonical.BlogVersionRepository, "get_latest_for_sessions", new=AsyncMock(return_value=latest_versions)),
                patch.object(
                    canonical.BudgetRepository,
                    "get_effective_policy",
                    new=AsyncMock(return_value=SimpleNamespace(max_revision_iterations_per_session=3)),
                ),
            ):
                response = await canonical._list_blog_sessions(
                    end_user_id=11,
                    tenant_id=5,
                    limit=20,
                    offset=0,
                    status_filter=None,
                )

        assert response.total == 1
        assert response.items[0].remaining_revision_iterations == 2
        assert response.items[0].latest_title == "Latest"


class TestRouteCoverage:
    @pytest.mark.asyncio
    async def test_cost_summary_exposes_corrected_active_sessions(self):
        with patch.dict(sys.modules, _install_google_adk_stubs()):
            main = _import_main_module()
        snapshot = BudgetSnapshot(
            end_user_id=11,
            tenant_id=5,
            daily_spent_usd=0.4,
            daily_spent_tokens=1200,
            daily_limit_usd=2.0,
            daily_limit_tokens=5000,
            active_sessions=2,
            max_concurrent_sessions=3,
            remaining_revision_iterations=4,
        )
        request = Request({"type": "http", "headers": []})
        request.state.user_id = "7"
        request.state.user_email = "user@example.com"
        request.state.user_display_name = "User"
        request.state.token_claims = {}
        request.state.authenticated = True

        with patch.dict(sys.modules, _install_google_adk_stubs()):
            with (
                patch(
                    "src.services.adapter_auth_service.AdapterAuthService.resolve_standalone_mode",
                    new=AsyncMock(
                        return_value=SimpleNamespace(
                            tenant_id=5,
                            end_user_id=11,
                            service_client_id=1,
                            mode="standalone",
                            external_user_id="7",
                        )
                    ),
                ),
                patch.object(main.db_repository, "async_session", return_value=_AsyncSessionContext()),
                patch.object(main.BudgetService, "get_snapshot", new=AsyncMock(return_value=snapshot)),
            ):
                response = await main.get_cost_summary(request)

        assert response["active_sessions"] == 2
        assert response["remaining_revision_iterations"] == 4


class TestDocsRealignment:
    def test_architecture_doc_is_current_backend_reference(self):
        backend_root = Path(__file__).resolve().parents[2]
        architecture = (backend_root / "docs" / "ARCHITECTURE-blogify.md").read_text()

        assert "FastAPI API service" in architecture
        assert "service_client_budget_policies" in architecture
        assert "GET /api/v1/blogs" in architecture
        assert "X-Admin-Api-Key" in architecture
        assert "Tempo" in architecture
        assert "budget_ledger_entries" in architecture

        first_lines = "\n".join(architecture.splitlines()[:20])
        assert "Prisma Accelerate" not in first_lines
        assert "Cloudflare Workers" not in first_lines

    def test_historical_docs_are_marked_non_authoritative(self):
        backend_root = Path(__file__).resolve().parents[2]
        docs = [
            backend_root / "docs" / "ARCHITECTURE.md",
            backend_root / "docs" / "REFACTOR_PLAN.md",
            backend_root / "docs" / "POST_REFACTOR_AUDIT.md",
        ]

        for doc in docs:
            content = doc.read_text()
            assert "Historical / Planning Artifact" in content
            assert "ARCHITECTURE-blogify.md" in content
