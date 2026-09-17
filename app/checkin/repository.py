from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import ChallengeMember
from app.checkin.models import CheckIn
from app.common.repositories import BaseRepository
from app.user.models import User


class CheckInRepository(BaseRepository[CheckIn]):
    async def find_by_challenge_and_dates(
        self, db: AsyncSession, challenge_id: UUID, local_dates: set[date]
    ) -> Sequence[CheckIn]:
        """Every proof for those days, oldest first, so later ones win."""
        if not local_dates:
            return []
        result = await db.execute(
            select(CheckIn)
            .where(CheckIn.challenge_id == challenge_id, CheckIn.local_date.in_(local_dates))
            .order_by(CheckIn.submitted_at.asc(), CheckIn.id.asc())
        )
        return result.scalars().all()


class ChallengeMemberWithUserRepository(BaseRepository[ChallengeMember]):
    async def find_members_with_users(
        self, db: AsyncSession, challenge_id: UUID
    ) -> Sequence[Row[tuple[ChallengeMember, User]]]:
        """Members with the user rows the day view needs: name and timezone."""
        result = await db.execute(
            select(ChallengeMember, User)
            .join(User, User.id == ChallengeMember.user_id)
            .where(ChallengeMember.challenge_id == challenge_id)
            .order_by(ChallengeMember.joined_at.asc(), ChallengeMember.id.asc())
        )
        return result.all()
