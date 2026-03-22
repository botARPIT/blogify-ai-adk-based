"""AdapterAuthService — resolves caller identity from API key or auth token."""

from __future__ import annotations

import hashlib
from typing import Optional

from src.models.orm_models import ClientMode
from src.models.repositories.identity_repository import IdentityRepository
from src.models.schemas import ResolvedIdentity


class AdapterAuthError(Exception):
    """Raised when API key resolution fails."""
    pass


class AdapterAuthService:
    """Resolves the caller identity for both standalone and Blogify service modes.

    Standalone mode:
        - Caller authenticates with a user JWT (handled by existing auth middleware)
        - service_client_key = "standalone-default"
        - external_user_id comes from JWT subject

    Blogify service mode:
        - Caller authenticates with X-Internal-API-Key header
        - Request body provides tenant_id, end_user_id, request_id
        - service_client resolved from hashed API key
    """

    def __init__(self, identity_repo: IdentityRepository) -> None:
        self._identity_repo = identity_repo

    @staticmethod
    def hash_api_key(raw_api_key: str) -> str:
        return hashlib.sha256(raw_api_key.encode()).hexdigest()

    async def resolve_service_mode(
        self,
        raw_api_key: str,
        external_tenant_id: Optional[str],
        external_user_id: str,
        external_request_id: Optional[str] = None,
    ) -> ResolvedIdentity:
        """Resolve identity for Blogify server-to-server calls."""
        hashed = self.hash_api_key(raw_api_key)
        client = await self._identity_repo.get_client_by_hashed_api_key(hashed)
        if not client:
            raise AdapterAuthError("Invalid or inactive API key")

        if client.mode != ClientMode.BLOGIFY_SERVICE.value:
            raise AdapterAuthError(
                f"API key is registered for mode '{client.mode}', not 'blogify_service'"
            )

        tenant = await self._identity_repo.get_or_create_tenant(
            service_client_id=client.id,
            external_tenant_id=external_tenant_id,
            name=external_tenant_id or "default-tenant",
        )

        end_user = await self._identity_repo.get_or_create_end_user(
            tenant_id=tenant.id,
            external_user_id=external_user_id,
        )

        return ResolvedIdentity(
            service_client_id=client.id,
            tenant_id=tenant.id,
            end_user_id=end_user.id,
            mode=ClientMode.BLOGIFY_SERVICE.value,
            external_user_id=external_user_id,
            external_tenant_id=external_tenant_id,
        )

    async def resolve_standalone_mode(
        self,
        external_user_id: str,
        email: Optional[str] = None,
    ) -> ResolvedIdentity:
        """Resolve identity for standalone mode calls."""
        client = await self._identity_repo.get_client_by_key("standalone-default")
        if not client:
            # Seed the standalone client on first use
            client = await self._identity_repo.create_service_client(
                client_key="standalone-default",
                name="Standalone Default Client",
                raw_api_key="standalone-internal-key",
                mode=ClientMode.STANDALONE,
            )

        tenant = await self._identity_repo.get_or_create_tenant(
            service_client_id=client.id,
            external_tenant_id=None,
            name="Standalone Tenant",
        )

        end_user = await self._identity_repo.get_or_create_end_user(
            tenant_id=tenant.id,
            external_user_id=external_user_id,
            email=email,
        )

        return ResolvedIdentity(
            service_client_id=client.id,
            tenant_id=tenant.id,
            end_user_id=end_user.id,
            mode=ClientMode.STANDALONE.value,
            external_user_id=external_user_id,
        )
