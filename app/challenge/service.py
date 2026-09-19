import secrets
from datetime import date, datetime, timedelta
from uuid import UUID
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
from app.challenge.schemas import (
    ChallengeCreate,
    ChallengeDetailResponse,
    ChallengeMemberResponse,
    ChallengePreviewResponse,
    ChallengeResponse,
    JoinChallengeRequest,
    JoinStatus,
    LeaderboardEntryResponse,
    MyChallengeResponse,
)
from app.shared.exception.errors import BusinessException, DuplicateResourceException, ResourceNotFoundException
from app.shared.storage.object_storage import object_storage
from app.streaks.service import streak_service
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


def _join_status(challenge: Challenge, today: date) -> JoinStatus:
    """Whether a non-member can join today. Shared by join and preview so they never disagree."""
    if challenge.status in (ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED):
        return JoinStatus.FINISHED
    # Compared against dates, not the stored status: the status is only refreshed
    # when someone reads the challenge, so between reads it can still lag behind
    # the calendar. The dates are the source of truth.
    if challenge.end_date is not None and today > challenge.end_date:
        return JoinStatus.FINISHED
    if today >= challenge.start_date and challenge.late_join_policy == LateJoinPolicy.CLOSED:
        return JoinStatus.CLOSED
    return JoinStatus.OPEN


def _missed_days_on_join(challenge: Challenge, today: date) -> int:
    if today < challenge.start_date or challenge.late_join_policy != LateJoinPolicy.INHERIT_MISSED:
        return 0
    # Today is excluded: the new member can still check in before midnight.
    return _count_active_days(challenge.start_date, today, challenge.active_days)


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

        today = _local_today(user)
        join_status = _join_status(challenge, today)
        if join_status == JoinStatus.FINISHED:
            raise BusinessException("This challenge has already finished.")
        if join_status == JoinStatus.CLOSED:
            raise BusinessException("This challenge has already started and is closed to new members.")
        missed_days = _missed_days_on_join(challenge, today)

        # Plain values: rollback() below expires every ORM object in the session,
        # and touching an expired attribute in async code raises MissingGreenlet.
        challenge_id, user_id = challenge.id, user.id

        db.add(
            ChallengeMember(
                challenge_id=challenge_id,
                user_id=user_id,
                role=MemberRole.MEMBER,
                missed_days_count=missed_days,
                inherited_missed_days=missed_days,
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

    async def preview(self, db: AsyncSession, user: User, data: JoinChallengeRequest) -> ChallengePreviewResponse:
        row = await self.challenge_repository.find_preview_by_invite_code(db, data.invite_code)
        if row is None:
            raise ResourceNotFoundException("Challenge", "invite code", data.invite_code)
        challenge, member_count, creator_display_name = row

        # Checked first, like join: a member opening their own invite link should
        # be sent to the challenge, even if it has finished.
        today = _local_today(user)
        if await self.member_repository.exists_by_challenge_and_user(db, challenge.id, user.id):
            join_status = JoinStatus.ALREADY_MEMBER
        else:
            join_status = _join_status(challenge, today)

        return ChallengePreviewResponse(
            id=challenge.id,
            title=challenge.title,
            description=challenge.description,
            duration_type=challenge.duration_type,
            total_days=challenge.total_days,
            start_date=challenge.start_date,
            end_date=challenge.end_date,
            active_days=challenge.active_days,
            requires_approval=challenge.requires_approval,
            late_join_policy=challenge.late_join_policy,
            member_count=member_count,
            creator_display_name=creator_display_name,
            join_status=join_status,
            missed_days_on_join=_missed_days_on_join(challenge, today) if join_status == JoinStatus.OPEN else None,
        )

    async def list_for_user(self, db: AsyncSession, user: User) -> list[MyChallengeResponse]:
        rows = await self.challenge_repository.find_all_for_user(db, user.id)

        # Refreshed here too, not only in the detail view: a list showing streaks
        # and statuses that the detail then corrects is the same app telling the
        # user two different things. The rows below are the same objects the
        # recalculation updates, so they already carry the new numbers.
        for challenge, _, _ in rows:
            await streak_service.recalculate(db, challenge)

        return [
            MyChallengeResponse(
                challenge=ChallengeResponse.model_validate(challenge),
                my_membership=ChallengeMemberResponse.model_validate(membership),
                member_count=member_count,
            )
            for challenge, membership, member_count in rows
        ]

    async def get_detail(self, db: AsyncSession, user: User, challenge_id: UUID) -> ChallengeDetailResponse:
        challenge = await self.challenge_repository.find_by_id(db, challenge_id)
        rows = await self.member_repository.find_leaderboard(db, challenge_id) if challenge else []

        # 404 rather than 403 for non-members, so a private challenge's existence
        # is not confirmed to someone who merely has its id.
        if challenge is None or all(member.user_id != user.id for member, *_ in rows):
            raise ResourceNotFoundException("Challenge", "id", challenge_id)

        # Deduced on read: nothing schedules this, so the only moment the scores
        # can be trusted is the moment someone asks for them.
        await streak_service.recalculate(db, challenge)
        rows = await self.member_repository.find_leaderboard(db, challenge_id)

        leaderboard: list[LeaderboardEntryResponse] = []
        rank = 0
        previous_missed: int | None = None
        for position, (member, display_name, avatar_key) in enumerate(rows, start=1):
            if member.missed_days_count != previous_missed:
                rank = position
                previous_missed = member.missed_days_count
            leaderboard.append(
                LeaderboardEntryResponse(
                    rank=rank,
                    user_id=member.user_id,
                    display_name=display_name,
                    avatar_url=object_storage.create_download_url(avatar_key) if avatar_key else None,
                    role=member.role,
                    current_individual_streak=member.current_individual_streak,
                    best_individual_streak=member.best_individual_streak,
                    missed_days_count=member.missed_days_count,
                    joined_at=member.joined_at,
                )
            )

        return ChallengeDetailResponse(challenge=ChallengeResponse.model_validate(challenge), leaderboard=leaderboard)
