from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Row, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import ChallengeMember
from app.checkin.models import CheckIn, CheckInReview, CheckInStatus
from app.common.repositories import BaseRepository
from app.user.models import User


class CheckInRepository(BaseRepository[CheckIn]):
    async def find_by_id(self, db: AsyncSession, check_in_id: UUID) -> CheckIn | None:
        result = await db.execute(select(CheckIn).where(CheckIn.id == check_in_id))
        return result.scalar_one_or_none()

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

    async def find_pending_with_authors(
        self, db: AsyncSession, challenge_id: UUID
    ) -> Sequence[Row[tuple[CheckIn, User]]]:
        """Proofs still waiting for the group, oldest first: the queue to review."""
        result = await db.execute(
            select(CheckIn, User)
            .join(User, User.id == CheckIn.user_id)
            .where(CheckIn.challenge_id == challenge_id, CheckIn.status == CheckInStatus.PENDING_REVIEW)
            .order_by(CheckIn.submitted_at.asc(), CheckIn.id.asc())
        )
        return result.all()

    async def settle_expired_reviews(self, db: AsyncSession, challenge_id: UUID, now: datetime) -> int:
        """Approves the proofs whose voting window ran out.

        Silence approves: the member uploaded on time, so the group taking too
        long to vote must not cost them the day. Written as one statement rather
        than a scheduled job, so it settles the moment anyone looks.
        """
        statement = (
            update(CheckIn)
            .where(
                CheckIn.challenge_id == challenge_id,
                CheckIn.status == CheckInStatus.PENDING_REVIEW,
                CheckIn.review_closes_at.is_not(None),
                CheckIn.review_closes_at <= now,
            )
            .values(status=CheckInStatus.APPROVED)
        )
        return (await db.execute(statement)).rowcount  # type: ignore[attr-defined]


class CheckInReviewRepository(BaseRepository[CheckInReview]):
    async def find_by_check_in_and_reviewer(
        self, db: AsyncSession, check_in_id: UUID, reviewer_id: UUID
    ) -> CheckInReview | None:
        result = await db.execute(
            select(CheckInReview).where(
                CheckInReview.check_in_id == check_in_id, CheckInReview.reviewer_id == reviewer_id
            )
        )
        return result.scalar_one_or_none()

    async def count_votes(
        self, db: AsyncSession, check_in_ids: list[UUID], reviewer_ids: set[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        """Approvals and rejections per proof, in one query for the whole queue.

        Only the votes of `reviewer_ids` are counted: a member who left no longer
        has a say, and the majority is taken over the members still in.
        """
        if not check_in_ids or not reviewer_ids:
            return {}
        result = await db.execute(
            select(
                CheckInReview.check_in_id,
                func.count().filter(CheckInReview.is_approved.is_(True)),
                func.count().filter(CheckInReview.is_approved.is_(False)),
            )
            .where(CheckInReview.check_in_id.in_(check_in_ids), CheckInReview.reviewer_id.in_(reviewer_ids))
            .group_by(CheckInReview.check_in_id)
        )
        return {check_in_id: (approvals, rejections) for check_in_id, approvals, rejections in result.all()}

    async def find_votes_by_reviewer(
        self, db: AsyncSession, check_in_ids: list[UUID], reviewer_id: UUID
    ) -> dict[UUID, bool]:
        """What this reviewer already voted, so the queue can show it back."""
        if not check_in_ids:
            return {}
        result = await db.execute(
            select(CheckInReview.check_in_id, CheckInReview.is_approved).where(
                CheckInReview.check_in_id.in_(check_in_ids), CheckInReview.reviewer_id == reviewer_id
            )
        )
        return {check_in_id: is_approved for check_in_id, is_approved in result.all()}


class ChallengeMemberWithUserRepository(BaseRepository[ChallengeMember]):
    async def find_members_with_users(
        self, db: AsyncSession, challenge_id: UUID
    ) -> Sequence[Row[tuple[ChallengeMember, User]]]:
        """Everyone who ever joined, including those who left, with name and timezone."""
        result = await db.execute(
            select(ChallengeMember, User)
            .join(User, User.id == ChallengeMember.user_id)
            .where(ChallengeMember.challenge_id == challenge_id)
            .order_by(ChallengeMember.joined_at.asc(), ChallengeMember.id.asc())
        )
        return result.all()
