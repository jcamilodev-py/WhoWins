from uuid import UUID

from fastapi import APIRouter, Request, status

from app.auth.dependencies import CurrentUser
from app.challenge.repository import ChallengeRepository
from app.checkin.repository import ChallengeMemberWithUserRepository, CheckInRepository, CheckInReviewRepository
from app.checkin.schemas import (
    CheckInConfirmRequest,
    CheckInResponse,
    CheckInUnderReviewResponse,
    CheckInUploadRequest,
    CheckInUploadResponse,
    ReviewVoteRequest,
    TodayStatusResponse,
)
from app.checkin.service import CheckInReviewService, CheckInService
from app.core.database import DBSession
from app.core.limiter import limiter

router = APIRouter(prefix="/api/v1/challenges/{challenge_id}/checkins", tags=["check-ins"])

check_in_service = CheckInService(ChallengeRepository(), ChallengeMemberWithUserRepository(), CheckInRepository())
review_service = CheckInReviewService(
    ChallengeRepository(), ChallengeMemberWithUserRepository(), CheckInRepository(), CheckInReviewRepository()
)


@router.post("/upload-url", response_model=CheckInUploadResponse)
# Each URL is a write permission on the bucket for a few minutes.
@limiter.limit("10/minute")
async def create_check_in_upload_url(
    request: Request, challenge_id: UUID, body: CheckInUploadRequest, db: DBSession, current_user: CurrentUser
):
    return await check_in_service.create_upload(db, current_user, challenge_id, body)


@router.post("/confirm", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
async def confirm_check_in(challenge_id: UUID, body: CheckInConfirmRequest, db: DBSession, current_user: CurrentUser):
    return await check_in_service.confirm(db, current_user, challenge_id, body)


@router.get("/today", response_model=TodayStatusResponse)
async def get_today_status(challenge_id: UUID, db: DBSession, current_user: CurrentUser):
    return await check_in_service.get_today(db, current_user, challenge_id)


@router.get("/pending", response_model=list[CheckInUnderReviewResponse])
async def list_pending_reviews(challenge_id: UUID, db: DBSession, current_user: CurrentUser):
    return await review_service.list_pending(db, current_user, challenge_id)


@router.put("/{check_in_id}/review", response_model=CheckInUnderReviewResponse)
async def review_check_in(
    challenge_id: UUID, check_in_id: UUID, body: ReviewVoteRequest, db: DBSession, current_user: CurrentUser
):
    """PUT, not POST: a member has one vote here, and voting again replaces it."""
    return await review_service.vote(db, current_user, challenge_id, check_in_id, body)
