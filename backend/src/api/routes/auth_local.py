"""Local cookie-auth routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from src.api.auth import ensure_csrf_header, get_current_user
from src.models.repository import db_repository
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.schemas import AuthMeResponse, AuthUserView, LoginRequest
from src.services.local_auth_service import LocalAuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def _to_view(user) -> AuthUserView:
    return AuthUserView(id=int(user.id), email=user.email, display_name=user.display_name)


@router.post("/login", response_model=AuthMeResponse)
async def login(payload: LoginRequest, response: Response):
    auth_service = LocalAuthService()
    async with db_repository.async_session() as session:
        async with session.begin():
            auth_repo = AuthUserRepository(session)
            await auth_service.ensure_seed_user(auth_repo)
            user = await auth_service.authenticate(
                auth_repo,
                email=payload.email,
                password=payload.password,
            )
            if user is None:
                raise HTTPException(status_code=401, detail="Invalid email or password")
            orm_user = await auth_repo.get_by_id(user.user_id)
            if orm_user is None:
                raise HTTPException(status_code=401, detail="User not found")
            token = auth_service.issue_token(user)
            auth_service.set_auth_cookie(response, token)
            return AuthMeResponse(authenticated=True, user=_to_view(orm_user))


@router.post("/logout")
async def logout(request: Request, response: Response):
    ensure_csrf_header(request)
    LocalAuthService().clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=AuthMeResponse)
async def me(request: Request):
    current_user = get_current_user(request)
    if current_user is None:
        return AuthMeResponse(authenticated=False, user=None)
    async with db_repository.async_session() as session:
        auth_repo = AuthUserRepository(session)
        orm_user = await auth_repo.get_by_id(int(current_user.user_id))
        if orm_user is None:
            return AuthMeResponse(authenticated=False, user=None)
        return AuthMeResponse(authenticated=True, user=_to_view(orm_user))
