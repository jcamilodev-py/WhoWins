from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.dependencies import CurrentUser, CurrentUserOptional
from app.auth.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserPublic,
)
from app.auth.service import AuthService
from app.core.database import DBSession
from app.core.limiter import limiter
from app.user.repository import UserRepository
from app.user.schemas import UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

auth_service = AuthService(UserRepository())


@router.post("/register", response_model=UserPublic, status_code=201)
@limiter.limit("3/minute")
async def register(request: Request, body: RegisterRequest, db: DBSession):
    return await auth_service.register(db, body)


@router.post("/login", response_model=AuthResponse, summary="Iniciar sesión")
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    db: DBSession,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    return await auth_service.login(db, form_data.username, form_data.password, response)


@router.post("/refresh", response_model=AuthResponse, summary="Renovar sesión")
@limiter.limit("10/minute")
async def refresh(request: Request, response: Response, db: DBSession):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No hay sesión activa")
    return await auth_service.refresh_session(token, response, db)


@router.post("/logout", status_code=204, summary="Cerrar sesión")
async def logout(response: Response, db: DBSession, user: CurrentUserOptional) -> None:
    if user:
        await auth_service.logout(db, user)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


@router.get("/me", response_model=UserResponse, summary="Perfil del usuario autenticado")
async def get_me(user: CurrentUser):
    return UserResponse.model_validate(user)


@router.post("/change-password", status_code=204)
async def change_password(request: ChangePasswordRequest, db: DBSession, user: CurrentUser):
    await auth_service.change_password(db, user, request)


@router.post("/forgot-password", status_code=204)
async def forgot_password(request: ForgotPasswordRequest, db: DBSession):
    await auth_service.forgot_password(db, request)


@router.post("/reset-password", status_code=204)
async def reset_password(request: ResetPasswordRequest, db: DBSession):
    await auth_service.reset_password(db, request)