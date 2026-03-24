"""IdentityRepository — manages ServiceClient, Tenant, EndUser resolution."""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm_models import (
    ClientMode,
    ClientStatus,
    EndUser,
    EndUserStatus,
    ServiceClient,
    Tenant,
    TenantPlan,
    TenantStatus,
)


class IdentityRepository:
    """Resolves and manages caller identity entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # ServiceClient
    # ------------------------------------------------------------------

    async def get_client_by_key(self, client_key: str) -> Optional[ServiceClient]:
        result = await self._session.execute(
            select(ServiceClient).where(ServiceClient.client_key == client_key)
        )
        return result.scalar_one_or_none()

    async def get_client_by_hashed_api_key(self, hashed_key: str) -> Optional[ServiceClient]:
        result = await self._session.execute(
            select(ServiceClient).where(
                ServiceClient.hashed_api_key == hashed_key,
                ServiceClient.status == ClientStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def create_service_client(
        self,
        client_key: str,
        name: str,
        raw_api_key: str,
        mode: ClientMode = ClientMode.STANDALONE,
    ) -> ServiceClient:
        hashed = hashlib.sha256(raw_api_key.encode()).hexdigest()
        client = ServiceClient(
            client_key=client_key,
            name=name,
            mode=mode,
            hashed_api_key=hashed,
            status=ClientStatus.ACTIVE,
        )
        self._session.add(client)
        await self._session.flush()
        return client

    # ------------------------------------------------------------------
    # Tenant
    # ------------------------------------------------------------------

    async def get_or_create_tenant(
        self,
        service_client_id: int,
        external_tenant_id: Optional[str],
        name: str,
        plan: TenantPlan = TenantPlan.FREE,
    ) -> Tenant:
        query = select(Tenant).where(Tenant.service_client_id == service_client_id)
        if external_tenant_id:
            query = query.where(Tenant.external_tenant_id == external_tenant_id)
        result = await self._session.execute(query)
        tenant = result.scalar_one_or_none()
        if tenant:
            return tenant

        tenant = Tenant(
            service_client_id=service_client_id,
            external_tenant_id=external_tenant_id,
            name=name,
            plan_tier=plan,
            status=TenantStatus.ACTIVE,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    # ------------------------------------------------------------------
    # EndUser
    # ------------------------------------------------------------------

    async def get_or_create_end_user(
        self,
        tenant_id: int,
        external_user_id: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> EndUser:
        result = await self._session.execute(
            select(EndUser).where(
                EndUser.tenant_id == tenant_id,
                EndUser.external_user_id == external_user_id,
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return user

        user = EndUser(
            tenant_id=tenant_id,
            external_user_id=external_user_id,
            email=email,
            display_name=display_name,
            status=EndUserStatus.ACTIVE,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_end_user_by_id(self, end_user_id: int) -> Optional[EndUser]:
        result = await self._session.execute(
            select(EndUser).where(EndUser.id == end_user_id)
        )
        return result.scalar_one_or_none()
