"""Operator-only service-client management routes."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException

from src.config.env_config import config
from src.models.repository import db_repository
from src.models.repositories.identity_repository import IdentityRepository
from src.models.repositories.service_client_budget_repository import (
    ServiceClientBudgetRepository,
)
from src.models.schemas import (
    CreateServiceClientRequest,
    CreateServiceClientResponse,
    RotateServiceClientResponse,
    ServiceClientListResponse,
    ServiceClientView,
    ServiceClientBudgetView,
    UpdateServiceClientBudgetRequest,
)
from src.services.service_client_budget_service import ServiceClientBudgetService
from src.services.service_client_service import ServiceClientService

router = APIRouter(prefix="/internal/admin/service-clients", tags=["Admin"])


def require_admin_api_key(x_admin_api_key: str | None = None) -> None:
    expected = getattr(config, "admin_api_key", None)
    if not x_admin_api_key or not expected or not secrets.compare_digest(x_admin_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid admin API key")


def _to_view(client) -> ServiceClientView:
    return ServiceClientView(
        client_key=client.client_key,
        name=client.name,
        mode=client.mode,
        status=client.status,
        created_at=client.created_at,
        rotated_at=client.rotated_at,
    )


@router.post("", response_model=CreateServiceClientResponse)
async def create_service_client(
    payload: CreateServiceClientRequest,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        async with session.begin():
            identity_repo = IdentityRepository(session)
            existing = await identity_repo.get_service_client_by_key(payload.client_key)
            if existing is not None:
                raise HTTPException(status_code=409, detail="Service client already exists")
            service = ServiceClientService(identity_repo)
            client, raw_key = await service.create_service_client(
                client_key=payload.client_key,
                name=payload.name,
                mode=payload.mode,
            )
            return CreateServiceClientResponse(**_to_view(client).model_dump(), api_key=raw_key)


@router.get("", response_model=ServiceClientListResponse)
async def list_service_clients(
    limit: int = 100,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        identity_repo = IdentityRepository(session)
        items = await identity_repo.list_service_clients(limit=min(max(limit, 1), 100))
        return ServiceClientListResponse(items=[_to_view(item) for item in items])


@router.get("/{client_key}", response_model=ServiceClientView)
async def get_service_client(
    client_key: str,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        identity_repo = IdentityRepository(session)
        client = await identity_repo.get_service_client_by_key(client_key)
        if client is None:
            raise HTTPException(status_code=404, detail="Service client not found")
        return _to_view(client)


@router.get("/{client_key}/budget", response_model=ServiceClientBudgetView)
async def get_service_client_budget(
    client_key: str,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        identity_repo = IdentityRepository(session)
        client = await identity_repo.get_service_client_by_key(client_key)
        if client is None:
            raise HTTPException(status_code=404, detail="Service client not found")
        budget_service = ServiceClientBudgetService(ServiceClientBudgetRepository(session))
        return await budget_service.get_state(int(client.id))


@router.post("/{client_key}/budget", response_model=ServiceClientBudgetView)
async def update_service_client_budget(
    client_key: str,
    payload: UpdateServiceClientBudgetRequest,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        async with session.begin():
            identity_repo = IdentityRepository(session)
            client = await identity_repo.get_service_client_by_key(client_key)
            if client is None:
                raise HTTPException(status_code=404, detail="Service client not found")
            budget_service = ServiceClientBudgetService(ServiceClientBudgetRepository(session))
            await budget_service.update_policy(
                int(client.id), payload.daily_budget_limit_usd
            )
            return await budget_service.get_state(int(client.id))


@router.post("/{client_key}/rotate", response_model=RotateServiceClientResponse)
async def rotate_service_client(
    client_key: str,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        async with session.begin():
            service = ServiceClientService(IdentityRepository(session))
            client, raw_key = await service.rotate_service_client_api_key(client_key)
            if client is None:
                raise HTTPException(status_code=404, detail="Service client not found")
            return RotateServiceClientResponse(**_to_view(client).model_dump(), api_key=raw_key)


@router.post("/{client_key}/suspend", response_model=ServiceClientView)
async def suspend_service_client(
    client_key: str,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        async with session.begin():
            client = await ServiceClientService(IdentityRepository(session)).suspend_service_client(client_key)
            if client is None:
                raise HTTPException(status_code=404, detail="Service client not found")
            return _to_view(client)


@router.post("/{client_key}/activate", response_model=ServiceClientView)
async def activate_service_client(
    client_key: str,
    x_admin_api_key: str | None = Header(default=None),
):
    require_admin_api_key(x_admin_api_key)
    async with db_repository.async_session() as session:
        async with session.begin():
            client = await ServiceClientService(IdentityRepository(session)).activate_service_client(client_key)
            if client is None:
                raise HTTPException(status_code=404, detail="Service client not found")
            return _to_view(client)
