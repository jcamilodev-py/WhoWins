from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories import BaseRepository
from app.user.models import User


class UserRepository(BaseRepository[User]):
    async def find_by_id(self, db: AsyncSession, user_id: UUID) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))

        return result.scalar_one_or_none()

    async def find_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def find_by_google_id(self, db: AsyncSession, google_id: str) -> User | None:
        result = await db.execute(select(User).where(User.google_id == google_id))
        return result.scalar_one_or_none()

    async def find_by_reset_token(self, db: AsyncSession, reset_token: str) -> User | None:
        result = await db.execute(select(User).where(User.reset_token == reset_token))
        return result.scalar_one_or_none()

    async def exists_by_email(self, db: AsyncSession, email: str) -> bool:
        result = await db.execute(select(exists().where(User.email == email)))
        return bool(result.scalar())