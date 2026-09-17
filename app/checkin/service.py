from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.challenge.models import Challenge, ChallengeStatus
from app.challenge.repository import ChallengeRepository
from app.checkin.models import CheckIn, CheckInStatus
from app.checkin.repository import ChallengeMemberWithUserRepository, CheckInRepository
from app.checkin.schemas import (
    CheckInConfirmRequest,
    CheckInResponse,
    CheckInUploadRequest,
    CheckInUploadResponse,
    DayStatus,
    MemberDayStatusResponse,
    TodayStatusResponse,
)
from app.core.settings import settings
from app.shared.exception.errors import BusinessException, ResourceNotFoundException
from app.shared.storage.images import image_extension, normalize_image_content_type, verify_uploaded_image
from app.shared.storage.object_storage import object_storage
from app.shared.timezones import local_today, start_of_day
from app.user.models import User

# A proof stops counting only when the group rejects it; while it waits, the
# member has done their part.
COUNTING_STATUSES = (CheckInStatus.APPROVED, CheckInStatus.PENDING_REVIEW)

# Voting closes at the end of the day after the day the proof is for, in the
# author's timezone. Two days later at 00:00 is that same instant.
REVIEW_WINDOW_DAYS = 2


def _photo_prefix(challenge_id: UUID, user_id: UUID) -> str:
    return f"challenges/{challenge_id}/checkins/{user_id}/"


class CheckInService:
    def __init__(
        self,
        challenge_repository: ChallengeRepository,
        member_repository: ChallengeMemberWithUserRepository,
        check_in_repository: CheckInRepository,
    ):
        self.challenge_repository = challenge_repository
        self.member_repository = member_repository
        self.check_in_repository = check_in_repository

    async def _load_for_member(self, db: AsyncSession, user: User, challenge_id: UUID) -> Challenge:
        challenge = await self.challenge_repository.find_by_id(db, challenge_id)
        rows = await self.member_repository.find_members_with_users(db, challenge_id) if challenge else []
        # 404 rather than 403, exactly as the challenge detail does: a non-member
        # must not be able to confirm that a challenge exists.
        if challenge is None or all(member.user_id != user.id for member, _ in rows):
            raise ResourceNotFoundException("Challenge", "id", challenge_id)
        return challenge

    async def _require_open_day(self, db: AsyncSession, user: User, challenge_id: UUID) -> tuple[Challenge, date]:
        """The challenge and the member's own today, if a proof is owed on it.

        Checked again on confirm, not only when the upload URL is signed: the
        upload takes time, and midnight can pass in between.
        """
        challenge = await self._load_for_member(db, user, challenge_id)
        today = local_today(user.timezone)

        if challenge.status in (ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED):
            raise BusinessException("This challenge is no longer running.")
        if today < challenge.start_date:
            raise BusinessException("This challenge has not started yet.")
        if challenge.end_date is not None and today > challenge.end_date:
            raise BusinessException("This challenge has already finished.")
        if today.weekday() not in challenge.active_days:
            raise BusinessException("Today is a rest day for this challenge.")

        return challenge, today

    async def create_upload(
        self, db: AsyncSession, user: User, challenge_id: UUID, data: CheckInUploadRequest
    ) -> CheckInUploadResponse:
        _, today = await self._require_open_day(db, user, challenge_id)
        content_type = normalize_image_content_type(data.content_type)

        key = f"{_photo_prefix(challenge_id, user.id)}{uuid7().hex}.{image_extension(content_type)}"
        upload = object_storage.create_upload_url(key, content_type)

        return CheckInUploadResponse(
            upload_url=upload.url,
            key=upload.key,
            content_type=upload.content_type,
            expires_in_seconds=upload.expires_in_seconds,
            max_bytes=settings.storage_max_upload_bytes,
            local_date=today,
        )

    async def confirm(
        self, db: AsyncSession, user: User, challenge_id: UUID, data: CheckInConfirmRequest
    ) -> CheckInResponse:
        challenge, today = await self._require_open_day(db, user, challenge_id)

        # The client picks the key it confirms, so it could name another member's
        # upload. Only keys under this member's own prefix are accepted.
        if not data.key.startswith(_photo_prefix(challenge_id, user.id)):
            raise BusinessException("This upload does not belong to the current user.")

        await verify_uploaded_image(data.key)

        auto_approved = not challenge.requires_approval
        check_in = CheckIn(
            challenge_id=challenge_id,
            user_id=user.id,
            local_date=today,
            photo_key=data.key,
            status=CheckInStatus.APPROVED if auto_approved else CheckInStatus.PENDING_REVIEW,
            review_closes_at=(
                None if auto_approved else start_of_day(today + timedelta(days=REVIEW_WINDOW_DAYS), user.timezone)
            ),
        )
        db.add(check_in)
        await db.commit()
        await db.refresh(check_in)

        return self._to_response(check_in)

    async def get_today(self, db: AsyncSession, user: User, challenge_id: UUID) -> TodayStatusResponse:
        challenge = await self._load_for_member(db, user, challenge_id)
        rows = await self.member_repository.find_members_with_users(db, challenge_id)

        # Each member is on their own calendar day, so the view asks for every
        # date in play at this instant, not just the viewer's.
        local_dates = {member_user.id: local_today(member_user.timezone) for _, member_user in rows}
        check_ins = await self.check_in_repository.find_by_challenge_and_dates(
            db, challenge_id, set(local_dates.values())
        )

        # Later proofs win: a rejected morning photo does not sink an accepted one.
        latest_counting: dict[UUID, CheckIn] = {}
        for check_in in check_ins:
            if check_in.status in COUNTING_STATUSES and check_in.local_date == local_dates.get(check_in.user_id):
                latest_counting[check_in.user_id] = check_in

        members = []
        for _, member_user in rows:
            local_date = local_dates[member_user.id]
            is_active_day = local_date.weekday() in challenge.active_days and local_date >= challenge.start_date
            counting = latest_counting.get(member_user.id)
            members.append(
                MemberDayStatusResponse(
                    user_id=member_user.id,
                    display_name=member_user.display_name,
                    local_date=local_date,
                    is_active_day=is_active_day,
                    status=self._day_status(is_active_day, counting),
                    check_in_id=counting.id if counting else None,
                    photo_url=object_storage.create_download_url(counting.photo_key) if counting else None,
                    submitted_at=counting.submitted_at if counting else None,
                )
            )

        return TodayStatusResponse(
            challenge_id=challenge_id,
            viewer_local_date=local_today(user.timezone),
            members=members,
        )

    @staticmethod
    def _day_status(is_active_day: bool, counting: CheckIn | None) -> DayStatus:
        if not is_active_day:
            return DayStatus.REST_DAY
        if counting is None:
            return DayStatus.MISSING
        return DayStatus.DONE if counting.status == CheckInStatus.APPROVED else DayStatus.AWAITING_REVIEW

    @staticmethod
    def _to_response(check_in: CheckIn) -> CheckInResponse:
        return CheckInResponse(
            id=check_in.id,
            challenge_id=check_in.challenge_id,
            user_id=check_in.user_id,
            local_date=check_in.local_date,
            status=check_in.status,
            review_closes_at=check_in.review_closes_at,
            submitted_at=check_in.submitted_at,
            photo_url=object_storage.create_download_url(check_in.photo_key),
        )
