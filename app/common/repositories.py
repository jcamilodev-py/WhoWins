from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    async def save(self, db: AsyncSession, model: T) -> T:
        db.add(model)
        await db.flush()
        await db.refresh(model)

        return model