import logging
import uuid
from datetime import UTC, datetime, timedelta
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
from app.user.models import DISPLAY_NAME_MAX_LENGTH, AuthProvider, Role, User
from app.user.repository import UserRepository

logger = logging.getLogger(__name__)

RESET_TOKEN_TTL = timedelta(hours=1)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """The hash verified against when the user does not exist, so /login costs
    the same time whether or not the account is real."""
    return hash_password("dummy-password-for-constant-time-comparison")


def _display_name_from_google(google_name: str | None) -> str | None:
    if google_name is None:
        return None
    return google_name.strip()[:DISPLAY_NAME_MAX_LENGTH].strip() or None


class AuthService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    @staticmethod
    def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
        secure = not settings.is_dev

        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=settings.access_token_expire_minutes * 60,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=settings.refresh_token_expire_days * 86400,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )

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

        user = User(
            email=request.email,
            display_name=request.display_name,
            password=hash_password(request.password),
            role=Role.USER,
            auth_provider=AuthProvider.LOCAL,
            email_verified=False,
        )
        # Left to the column default (UTC) when the client does not know it yet;
        # the profile can fix it later.
        if request.timezone is not None:
            user.timezone = request.timezone
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return UserPublic.model_validate(user)

    async def authenticate_user(self, db: AsyncSession, email: str, password: str) -> User:
        user = await self.repository.find_by_email(db, email)

        # Always verified, even with no user, so the response time does not
        # reveal which emails are registered.
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

    async def login_with_google(
        self, db: AsyncSession, email: str, google_id: str, google_name: str | None, response: Response
    ) -> AuthResponse:
        user = await self.repository.find_by_google_id(db, google_id)

        if user is None:
            existing_user = await self.repository.find_by_email(db, email)
            if existing_user is not None:
                existing_user.google_id = google_id
                existing_user.email_verified = True
                user = existing_user
            else:
                user = User(
                    email=email,
                    google_id=google_id,
                    role=Role.USER,
                    auth_provider=AuthProvider.GOOGLE,
                    email_verified=True,
                )

        # Google's name only fills a missing one: a name the user already chose wins.
        if user.display_name is None:
            user.display_name = _display_name_from_google(google_name)

        db.add(user)
        await db.commit()
        await db.refresh(user)

        if not user.active:
            raise BusinessException("User account is disabled")

        return self._issue_tokens(response, user)

    async def refresh_session(self, refresh_token: str, response: Response, db: AsyncSession) -> AuthResponse:
        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError as err:
            raise AuthenticationRequiredException() from err

        email = payload.get("sub")
        if not email or payload.get("type") != "refresh":
            raise AuthenticationRequiredException()

        user = await self.repository.find_by_email(db, email)
        if user is None or not user.active:
            raise AuthenticationRequiredException()

        if payload.get("tv", 0) != user.token_version:
            raise AuthenticationRequiredException()

        return self._issue_tokens(response, user)

    async def forgot_password(
        self, db: AsyncSession, request: ForgotPasswordRequest, background_tasks: BackgroundTasks
    ) -> None:
        user = await self.repository.find_by_email(db, request.email)
        if user is None:
            return

        reset_token = str(uuid.uuid4())
        user.reset_token = hash_token(reset_token)
        user.reset_token_expiry = datetime.now(UTC) + RESET_TOKEN_TTL
        db.add(user)
        await db.commit()

        # Outside the request: neither an SMTP failure nor the sending delay may
        # reveal whether the email exists.
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

        if user.reset_token_expiry is None or user.reset_token_expiry < datetime.now(UTC):
            raise BusinessException("Reset token has expired")

        user.password = hash_password(request.new_password)
        user.reset_token = None
        user.reset_token_expiry = None
        # Ends every open session: if the account was compromised, resetting the
        # password has to lock the attacker out.
        user.token_version += 1
        db.add(user)
        await db.commit()

    async def change_password(
        self, db: AsyncSession, user: User, request: ChangePasswordRequest, response: Response
    ) -> AuthResponse:
        if user.password is None or not verify_password(request.current_password, user.password):
            raise BusinessException("Current password is incorrect")

        user.password = hash_password(request.new_password)
        # Ends the other sessions; this one survives because it gets new tokens
        # below, already carrying the new token_version.
        user.token_version += 1
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return self._issue_tokens(response, user)

    async def logout(self, db: AsyncSession, user: User) -> None:
        user.token_version += 1
        db.add(user)
        await db.commit()
