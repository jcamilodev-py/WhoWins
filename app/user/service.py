from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exception.errors import ResourceNotFoundException
from app.user.models import User
from app.user.repository import UserRepository
from app.user.schemas import UserResponse, UserUpdateMe

user_repository = UserRepository()


def _to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


async def update_me(db: AsyncSession, user: User, data: UserUpdateMe) -> UserResponse:
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.timezone is not None:
        user.timezone = data.timezone
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _to_response(user)


async def find_by_id(db: AsyncSession, user_id: UUID) -> UserResponse:
    user = await user_repository.find_by_id(db, user_id)
    if user is None:
        raise ResourceNotFoundException("User", "id", user_id)

    return _to_response(user)


async def find_by_email(db: AsyncSession, email: str) -> UserResponse:
    user = await user_repository.find_by_email(db, email)
    if user is None:
        raise ResourceNotFoundException("User", "email", email)

    return _to_response(user)


async def find_by_google_id(db: AsyncSession, google_id: str) -> UserResponse:
    user = await user_repository.find_by_google_id(db, google_id)
    if user is None:
        raise ResourceNotFoundException("User", "google id", google_id)

    return _to_response(user)


async def exists_by_email(db: AsyncSession, email: str) -> bool:
    return await user_repository.exists_by_email(db, email)
