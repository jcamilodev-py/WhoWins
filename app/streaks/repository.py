from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import ChallengeMember
from app.checkin.models import CheckIn, CheckInStatus
from app.common.repositories import BaseRepository
from app.user.models import User

# A proof stops covering its day only when the group rejects it.
COUNTING_STATUSES = (CheckInStatus.APPROVED, CheckInStatus.PENDING_REVIEW)


class StreakRepository(BaseRepository[ChallengeMember]):
    async def find_members_with_users(
        self, db: AsyncSession, challenge_id: UUID
    ) -> Sequence[Row[tuple[ChallengeMember, User]]]:
        """Members with the user rows the arithmetic needs: timezone and join time."""
        result = await db.execute(
            select(ChallengeMember, User)
            .join(User, User.id == ChallengeMember.user_id)
            .where(ChallengeMember.challenge_id == challenge_id)
        )
        return result.all()

    async def find_counting_days(self, db: AsyncSession, challenge_id: UUID) -> Sequence[Row[tuple[UUID, date]]]:
        """Only the (user, day) pairs that still count, not the photos themselves."""
        result = await db.execute(
            select(CheckIn.user_id, CheckIn.local_date)
            .where(CheckIn.challenge_id == challenge_id, CheckIn.status.in_(COUNTING_STATUSES))
            .distinct()
        )
        return result.all()
