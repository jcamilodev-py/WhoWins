from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Row, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.challenge.models import Challenge, ChallengeMember
from app.common.repositories import BaseRepository


class ChallengeRepository(BaseRepository[Challenge]):
    async def find_by_id(self, db: AsyncSession, challenge_id: UUID) -> Challenge | None:
        result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
        return result.scalar_one_or_none()

    async def find_by_invite_code(self, db: AsyncSession, invite_code: str) -> Challenge | None:
        result = await db.execute(select(Challenge).where(Challenge.invite_code == invite_code))
        return result.scalar_one_or_none()

    async def exists_by_invite_code(self, db: AsyncSession, invite_code: str) -> bool:
        result = await db.execute(select(exists().where(Challenge.invite_code == invite_code)))
        return bool(result.scalar())

    async def find_all_for_user(
        self, db: AsyncSession, user_id: UUID
    ) -> Sequence[Row[tuple[Challenge, ChallengeMember, int]]]:
        """Each challenge the user belongs to, with their membership and the member count."""
        # A separate alias: the outer ChallengeMember is the user's own row, while
        # the count has to see every member of the challenge.
        counted = aliased(ChallengeMember)
        member_count = select(func.count(counted.id)).where(counted.challenge_id == Challenge.id).scalar_subquery()

        result = await db.execute(
            select(Challenge, ChallengeMember, member_count)
            .join(ChallengeMember, ChallengeMember.challenge_id == Challenge.id)
            .where(ChallengeMember.user_id == user_id)
            .order_by(ChallengeMember.joined_at.desc(), Challenge.id.desc())
        )
        return result.all()


class ChallengeMemberRepository(BaseRepository[ChallengeMember]):
    async def exists_by_challenge_and_user(self, db: AsyncSession, challenge_id: UUID, user_id: UUID) -> bool:
        result = await db.execute(
            select(exists().where(ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id))
        )
        return bool(result.scalar())

    async def find_leaderboard(self, db: AsyncSession, challenge_id: UUID) -> Sequence[ChallengeMember]:
        # Fewest missed days wins. Ties stay in join order until a tie-breaker is defined.
        result = await db.execute(
            select(ChallengeMember)
            .where(ChallengeMember.challenge_id == challenge_id)
            .order_by(
                ChallengeMember.missed_days_count.asc(), ChallengeMember.joined_at.asc(), ChallengeMember.id.asc()
            )
        )
        return result.scalars().all()
