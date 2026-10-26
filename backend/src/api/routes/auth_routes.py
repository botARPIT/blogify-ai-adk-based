"""HTTP boundary for local registration and cookie authentication."""

from fastapi import APIRouter, Depends, HTTPException, Response

from src.api.auth import AuthenticatedUser, get_current_user
from src.api.dependencies import get_auth_service
from src.models.orm_models import AuthUser
from src.models.schemas import AuthMeResponse, LoginRequest, RegisterRequest, UserResponse
from src.services.auth_service import AuthService
from src.services.local_auth_service import LocalAuthService

router = APIRouter(prefix="/auth", tags=["auth"])
local_auth = LocalAuthService()


def _user_response(user: AuthUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/register", response_model=AuthMeResponse, status_code=201)
async def register(
    body: RegisterRequest, response: Response, service: AuthService = Depends(get_auth_service)
) -> AuthMeResponse:
    try:
        user = await service.register(body.email, body.password, body.display_name)
        local_auth.set_auth_cookie(response, await service.login(body.email, body.password))
        return AuthMeResponse(authenticated=True, user=_user_response(user))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/login", response_model=AuthMeResponse)
async def login(
    body: LoginRequest, response: Response, service: AuthService = Depends(get_auth_service)
) -> AuthMeResponse:
    try:
        token = await service.login(body.email, body.password)
        user = await service.get_current_user_from_email(body.email)
        local_auth.set_auth_cookie(response, token)
        return AuthMeResponse(authenticated=True, user=_user_response(user))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc


@router.get("/me", response_model=AuthMeResponse)
async def get_me(
    user: AuthenticatedUser | None = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> AuthMeResponse:
    if user is None:
        return AuthMeResponse(authenticated=False, user=None)
    try:
        return AuthMeResponse(
            authenticated=True,
            user=_user_response(await service.get_current_user(int(user.user_id))),
        )
    except ValueError:
        return AuthMeResponse(authenticated=False, user=None)


@router.post("/logout", status_code=200)
async def logout(response: Response) -> dict[str, bool]:
    local_auth.clear_auth_cookie(response)
    return {"ok": True}
