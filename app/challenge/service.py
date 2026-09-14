import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import (
    Challenge,
    ChallengeMember,
    ChallengeStatus,
    DurationType,
    LateJoinPolicy,
    MemberRole,
)
from app.challenge.repository import ChallengeMemberRepository, ChallengeRepository
from app.challenge.schemas import ChallengeCreate, ChallengeResponse, JoinChallengeRequest
from app.shared.exception.errors import BusinessException, DuplicateResourceException, ResourceNotFoundException
from app.user.models import User

# No 0/O or 1/I/L: codes get read aloud and typed by hand.
INVITE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH = 4
INVITE_CODE_MAX_ATTEMPTS = 5

# Calendar days, counted inclusively from start_date.
DURATION_DAYS: dict[DurationType, int | None] = {
    DurationType.DAYS_10: 10,
    DurationType.DAYS_20: 20,
    DurationType.DAYS_30: 30,
    DurationType.INDEFINITE: None,
}


def _local_today(user: User) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


def _count_active_days(start: date, end_exclusive: date, active_days: list[int]) -> int:
    elapsed = (end_exclusive - start).days
    return sum(1 for offset in range(elapsed) if (start + timedelta(days=offset)).weekday() in active_days)


class ChallengeService:
    def __init__(self, challenge_repository: ChallengeRepository, member_repository: ChallengeMemberRepository):
        self.challenge_repository = challenge_repository
        self.member_repository = member_repository

    async def _generate_invite_code(self, db: AsyncSession) -> str:
        for _ in range(INVITE_CODE_MAX_ATTEMPTS):
            suffix = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))
            code = f"WINS-{suffix}"
            if not await self.challenge_repository.exists_by_invite_code(db, code):
                return code
        raise BusinessException("Could not generate a unique invite code, please try again.")

    async def create(self, db: AsyncSession, user: User, data: ChallengeCreate) -> ChallengeResponse:
        # Checked here rather than in the schema: "today" depends on the user's timezone.
        today = _local_today(user)
        if data.start_date < today:
            raise BusinessException("Start date cannot be in the past.")

        total_days = DURATION_DAYS[data.duration_type]
        end_date = data.start_date + timedelta(days=total_days - 1) if total_days is not None else None

        challenge = Challenge(
            title=data.title,
            description=data.description,
            invite_code=await self._generate_invite_code(db),
            visibility=data.visibility,
            duration_type=data.duration_type,
            total_days=total_days,
            start_date=data.start_date,
            end_date=end_date,
            active_days=data.active_days,
            requires_approval=data.requires_approval,
            late_join_policy=data.late_join_policy,
            status=ChallengeStatus.ACTIVE if data.start_date == today else ChallengeStatus.PENDING,
            created_by=user.id,
        )
        db.add(challenge)
        # Flush assigns the id the membership row needs without committing, so the
        # challenge and its creator are saved together or not at all.
        await db.flush()

        db.add(ChallengeMember(challenge_id=challenge.id, user_id=user.id, role=MemberRole.CREATOR))
        await db.commit()
        await db.refresh(challenge)

        return ChallengeResponse.model_validate(challenge)

    async def join(self, db: AsyncSession, user: User, data: JoinChallengeRequest) -> ChallengeResponse:
        challenge = await self.challenge_repository.find_by_invite_code(db, data.invite_code)
        if challenge is None:
            raise ResourceNotFoundException("Challenge", "invite code", data.invite_code)

        if await self.member_repository.exists_by_challenge_and_user(db, challenge.id, user.id):
            raise DuplicateResourceException("Challenge member", "user id", user.id)

        if challenge.status in (ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED):
            raise BusinessException("This challenge is no longer accepting members.")

        # Compared against dates, not the stored status: nothing flips PENDING to
        # ACTIVE yet, so status alone would report a started challenge as pending.
        today = _local_today(user)
        if challenge.end_date is not None and today > challenge.end_date:
            raise BusinessException("This challenge has already ended.")

        missed_days = 0
        if today >= challenge.start_date:
            if challenge.late_join_policy == LateJoinPolicy.CLOSED:
                raise BusinessException("This challenge has already started and is closed to new members.")
            if challenge.late_join_policy == LateJoinPolicy.INHERIT_MISSED:
                # Today is excluded: the new member can still check in before midnight.
                missed_days = _count_active_days(challenge.start_date, today, challenge.active_days)

        # Plain values: rollback() below expires every ORM object in the session,
        # and touching an expired attribute in async code raises MissingGreenlet.
        challenge_id, user_id = challenge.id, user.id

        db.add(
            ChallengeMember(
                challenge_id=challenge_id,
                user_id=user_id,
                role=MemberRole.MEMBER,
                missed_days_count=missed_days,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # Two concurrent joins (a double tap) can both pass the membership check
            # above; the unique constraint rejects the second one.
            await db.rollback()
            if await self.member_repository.exists_by_challenge_and_user(db, challenge_id, user_id):
                raise DuplicateResourceException("Challenge member", "user id", user_id) from None
            raise

        await db.refresh(challenge)

        return ChallengeResponse.model_validate(challenge)
