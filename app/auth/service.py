import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import BackgroundTasks, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password, hash_token, verify_password
from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from app.auth.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserPublic,
)
from app.core.settings import settings
from app.shared.email.email_service import send_password_reset_email
from app.shared.exception.errors import AuthenticationRequiredException, BusinessException
from app.user.models import AuthProvider, Role, User
from app.user.repository import UserRepository

logger = logging.getLogger(__name__)

RESET_TOKEN_TTL = timedelta(hours=1)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Hash contra el que se verifica cuando el usuario no existe, para que el
    coste en tiempo de /login sea el mismo exista o no la cuenta."""
    return hash_password("dummy-password-for-constant-time-comparison")


class AuthService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    @staticmethod
    def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
        secure = not settings.is_dev

        response.set_cookie(key="access_token", value=access_token, max_age=settings.access_token_expire_minutes * 60, httponly=True, secure=secure, samesite="lax", path="/")
        response.set_cookie(key="refresh_token", value=refresh_token, max_age=settings.refresh_token_expire_days * 86400, httponly=True, secure=secure, samesite="lax", path="/")

    @staticmethod
    def clear_auth_cookies(response: Response) -> None:
        secure = not settings.is_dev

        response.delete_cookie(key="access_token", path="/", httponly=True, secure=secure, samesite="lax")
        response.delete_cookie(key="refresh_token", path="/", httponly=True, secure=secure, samesite="lax")

    def _issue_tokens(self, response: Response, user: User) -> AuthResponse:
        access_token = create_access_token({"sub": user.email, "tv": user.token_version})
        refresh_token = create_refresh_token({"sub": user.email, "tv": user.token_version})
        self._set_auth_cookies(response, access_token, refresh_token)

        return AuthResponse(access_token=access_token, user=UserPublic.model_validate(user))

    async def register(self, db: AsyncSession, request: RegisterRequest) -> UserPublic:
        if await self.repository.exists_by_email(db, request.email):
            raise BusinessException(f"Email already registered: {request.email}")

        user = User(email=request.email, password=hash_password(request.password), role=Role.USER, auth_provider=AuthProvider.LOCAL, email_verified=False)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return UserPublic.model_validate(user)

    async def authenticate_user(self, db: AsyncSession, email: str, password: str) -> User:
        user = await self.repository.find_by_email(db, email)

        # Se verifica siempre, incluso sin usuario, para no filtrar por tiempo
        # de respuesta que emails estan registrados.
        stored_hash = user.password if user is not None and user.password is not None else _dummy_password_hash()
        password_matches = verify_password(password, stored_hash)

        if user is None or user.password is None or not password_matches:
            raise AuthenticationRequiredException()

        if not user.active:
            raise BusinessException("User account is disabled")

        return user

    async def login(self, db: AsyncSession, email: str, password: str, response: Response) -> AuthResponse:
        user = await self.authenticate_user(db, email, password)
        return self._issue_tokens(response, user)

    async def login_with_google(self, db: AsyncSession, email: str, google_id: str, response: Response) -> AuthResponse:
        user = await self.repository.find_by_google_id(db, google_id)

        if user is None:
            existing_user = await self.repository.find_by_email(db, email)
            if existing_user is not None:
                existing_user.google_id = google_id
                existing_user.email_verified = True
                db.add(existing_user)
                await db.commit()
                await db.refresh(existing_user)
                user = existing_user
            else:
                new_user = User(email=email, google_id=google_id, role=Role.USER, auth_provider=AuthProvider.GOOGLE, email_verified=True)
                db.add(new_user)
                await db.commit()
                await db.refresh(new_user)
                user = new_user

        if not user.active:
            raise BusinessException("User account is disabled")

        return self._issue_tokens(response, user)

    async def refresh_session(self, refresh_token: str, response: Response, db: AsyncSession) -> AuthResponse:
        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError:
            raise AuthenticationRequiredException()

        email = payload.get("sub")
        if not email or payload.get("type") != "refresh":
            raise AuthenticationRequiredException()

        user = await self.repository.find_by_email(db, email)
        if user is None or not user.active:
            raise AuthenticationRequiredException()

        if payload.get("tv", 0) != user.token_version:
            raise AuthenticationRequiredException()

        return self._issue_tokens(response, user)

    async def forgot_password(self, db: AsyncSession, request: ForgotPasswordRequest, background_tasks: BackgroundTasks) -> None:
        user = await self.repository.find_by_email(db, request.email)
        if user is None:
            return

        reset_token = str(uuid.uuid4())
        user.reset_token = hash_token(reset_token)
        user.reset_token_expiry = datetime.now(timezone.utc) + RESET_TOKEN_TTL
        db.add(user)
        await db.commit()

        # Fuera del ciclo de request: ni un fallo de SMTP ni la latencia del
        # envio pueden revelar si el email existe.
        background_tasks.add_task(self._send_reset_email, user.email, reset_token)

    @staticmethod
    async def _send_reset_email(email: str, reset_token: str) -> None:
        try:
            await send_password_reset_email(email, reset_token)
        except Exception:
            logger.exception("Failed to send password reset email")

    async def reset_password(self, db: AsyncSession, request: ResetPasswordRequest) -> None:
        user = await self.repository.find_by_reset_token(db, hash_token(request.token))
        if user is None:
            raise BusinessException("Invalid or expired reset token")

        if user.reset_token_expiry is None or user.reset_token_expiry < datetime.now(timezone.utc):
            raise BusinessException("Reset token has expired")

        user.password = hash_password(request.new_password)
        user.reset_token = None
        user.reset_token_expiry = None
        # Invalida cualquier sesion abierta: si la cuenta estaba comprometida,
        # resetear la clave tiene que expulsar al atacante.
        user.token_version += 1
        db.add(user)
        await db.commit()

    async def change_password(self, db: AsyncSession, user: User, request: ChangePasswordRequest, response: Response) -> AuthResponse:
        if user.password is None or not verify_password(request.current_password, user.password):
            raise BusinessException("Current password is incorrect")

        user.password = hash_password(request.new_password)
        # Cierra el resto de sesiones; la actual sigue viva porque abajo se le
        # entregan tokens nuevos ya con el token_version actualizado.
        user.token_version += 1
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return self._issue_tokens(response, user)

    async def logout(self, db: AsyncSession, user: User) -> None:
        user.token_version += 1
        db.add(user)
        await db.commit()
