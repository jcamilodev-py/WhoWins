from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from app.auth.jwt_handler import decode_token
from app.core.database import DBSession
from app.shared.exception.errors import AuthenticationRequiredException
from app.user.models import Role, User
from app.user.repository import UserRepository

user_repository = UserRepository()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _extract_token(request: Request, token_from_header: str | None) -> str | None:
    token = request.cookies.get("access_token")
    if token:
        return token
    return token_from_header


async def get_current_user(request: Request, db: DBSession, token_from_header: str | None = Depends(oauth2_scheme)) -> User | None:
    token = _extract_token(request, token_from_header)
    if not token:
        return None

    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return None

    email = payload.get("sub")
    if not email or payload.get("type") != "access":
        return None

    user = await user_repository.find_by_email(db, email)
    if not user or not user.active:
        return None

    if payload.get("tv", 0) != user.token_version:
        return None

    return user


async def require_authenticated_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise AuthenticationRequiredException()
    return user


def require_role(*roles: Role):
    async def checker(user: User = Depends(require_authenticated_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="No tienes permisos para esta acción")
        return user

    return checker


CurrentUser = Annotated[User, Depends(require_authenticated_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user)]
RequireRoleAdmin = Annotated[User, Depends(require_role(Role.ADMIN))]
