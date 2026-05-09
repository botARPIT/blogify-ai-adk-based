"""Auth routes — registration, login, current user."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user, AuthenticatedUser
from src.core.database import get_db_session
from src.models.orm_models import AuthUser
from src.models.repositories.auth_user_repository import AuthUserRepository
from src.models.repositories.budget_repository import BudgetRepository
from src.models.repositories.budget_account_repository import BudgetAccountRepository
from src.models.schemas import AuthMeResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from src.services.auth_service import AuthService
from src.services.local_auth_service import LocalAuthService

router = APIRouter(prefix="/auth", tags=["auth"])
local_auth = LocalAuthService()


@router.post("/register", response_model=AuthMeResponse, status_code=201)
async def register(body: RegisterRequest, response: Response, session: AsyncSession = Depends(get_db_session)):
    user_repo = AuthUserRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    auth_service = AuthService(user_repo, budget_repo, account_repo)

    try:
        user = await auth_service.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
        token = await auth_service.login(body.email, body.password)
        local_auth.set_auth_cookie(response, token)
        return AuthMeResponse(
            authenticated=True,
            user=UserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/login", response_model=AuthMeResponse)
async def login(body: LoginRequest, response: Response, session: AsyncSession = Depends(get_db_session)):
    user_repo = AuthUserRepository(session)
    budget_repo = BudgetRepository(session)
    account_repo = BudgetAccountRepository(session)
    auth_service = AuthService(user_repo, budget_repo, account_repo)

    try:
        token = await auth_service.login(body.email, body.password)
        local_auth.set_auth_cookie(response, token)
        user = await user_repo.get_by_email(body.email)
        return AuthMeResponse(
            authenticated=True,
            user=UserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
            ),
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me", response_model=AuthMeResponse)
async def get_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    if not current_user:
        return AuthMeResponse(authenticated=False, user=None)
    
    user_repo = AuthUserRepository(session)
    user = await user_repo.get_by_id(int(current_user.user_id))
    if not user:
        return AuthMeResponse(authenticated=False, user=None)
    
    return AuthMeResponse(
        authenticated=True,
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        ),
    )