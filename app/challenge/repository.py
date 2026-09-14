from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import Challenge, ChallengeMember
from app.common.repositories import BaseRepository


class ChallengeRepository(BaseRepository[Challenge]):
    async def find_by_invite_code(self, db: AsyncSession, invite_code: str) -> Challenge | None:
        result = await db.execute(select(Challenge).where(Challenge.invite_code == invite_code))
        return result.scalar_one_or_none()

    async def exists_by_invite_code(self, db: AsyncSession, invite_code: str) -> bool:
        result = await db.execute(select(exists().where(Challenge.invite_code == invite_code)))
        return bool(result.scalar())


class ChallengeMemberRepository(BaseRepository[ChallengeMember]):
    async def exists_by_challenge_and_user(self, db: AsyncSession, challenge_id: UUID, user_id: UUID) -> bool:
        result = await db.execute(
            select(exists().where(ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id))
        )
        return bool(result.scalar())
