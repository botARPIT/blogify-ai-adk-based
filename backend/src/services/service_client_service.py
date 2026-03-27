"""Service-client lifecycle helpers for operator APIs."""

from __future__ import annotations

import secrets

from src.models.orm_models import ClientMode, ClientStatus, ServiceClient
from src.models.repositories.identity_repository import IdentityRepository


class ServiceClientService:
    """Own raw API key generation and service-client lifecycle operations."""

    def __init__(self, identity_repo: IdentityRepository) -> None:
        self._identity_repo = identity_repo

    def generate_api_key(self) -> str:
        return secrets.token_urlsafe(32)

    async def create_service_client(
        self,
        *,
        client_key: str,
        name: str,
        mode: ClientMode,
    ) -> tuple[ServiceClient, str]:
        raw_key = self.generate_api_key()
        client = await self._identity_repo.create_service_client(
            client_key=client_key,
            name=name,
            raw_api_key=raw_key,
            mode=mode,
        )
        return client, raw_key

    async def rotate_service_client_api_key(
        self, client_key: str
    ) -> tuple[ServiceClient | None, str]:
        raw_key = self.generate_api_key()
        client = await self._identity_repo.rotate_service_client_api_key(client_key, raw_key)
        return client, raw_key

    async def suspend_service_client(self, client_key: str) -> ServiceClient | None:
        return await self._identity_repo.set_service_client_status(
            client_key, ClientStatus.SUSPENDED
        )

    async def activate_service_client(self, client_key: str) -> ServiceClient | None:
        return await self._identity_repo.set_service_client_status(
            client_key, ClientStatus.ACTIVE
        )
