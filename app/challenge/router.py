from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.auth.dependencies import CurrentUser
from app.challenge.repository import ChallengeMemberRepository, ChallengeRepository
from app.challenge.schemas import (
    ChallengeCreate,
    ChallengeDetailResponse,
    ChallengeHistoryResponse,
    ChallengePreviewResponse,
    ChallengeResponse,
    JoinChallengeRequest,
    MyChallengeResponse,
)
from app.challenge.service import ChallengeService
from app.core.database import DBSession
from app.core.limiter import limiter

router = APIRouter(prefix="/api/v1/challenges", tags=["challenges"])

challenge_service = ChallengeService(ChallengeRepository(), ChallengeMemberRepository())


@router.get("", response_model=list[MyChallengeResponse])
async def list_my_challenges(db: DBSession, current_user: CurrentUser):
    return await challenge_service.list_for_user(db, current_user)


@router.get("/{challenge_id}", response_model=ChallengeDetailResponse)
async def get_challenge(challenge_id: UUID, db: DBSession, current_user: CurrentUser):
    return await challenge_service.get_detail(db, current_user, challenge_id)


@router.get("/{challenge_id}/history", response_model=ChallengeHistoryResponse)
async def get_challenge_history(
    challenge_id: UUID,
    db: DBSession,
    current_user: CurrentUser,
    # Enough for any fixed-length challenge by default; bounded because an
    # indefinite one keeps adding days forever.
    days: Annotated[int, Query(ge=1, le=366)] = 60,
):
    return await challenge_service.get_history(db, current_user, challenge_id, days)


@router.post("", response_model=ChallengeResponse, status_code=status.HTTP_201_CREATED)
async def create_challenge(body: ChallengeCreate, db: DBSession, current_user: CurrentUser):
    return await challenge_service.create(db, current_user, body)


@router.post("/preview", response_model=ChallengePreviewResponse)
# POST rather than GET with a query string: URLs end up in access logs and browser
# history, and the invite code is the only thing guarding a private challenge.
# Rate-limited like join, since it would otherwise be a faster way to guess codes.
@limiter.limit("10/minute")
async def preview_challenge(request: Request, body: JoinChallengeRequest, db: DBSession, current_user: CurrentUser):
    return await challenge_service.preview(db, current_user, body)


@router.post("/join", response_model=ChallengeResponse)
# Private challenges are only as private as their code is hard to guess.
@limiter.limit("10/minute")
async def join_challenge(request: Request, body: JoinChallengeRequest, db: DBSession, current_user: CurrentUser):
    return await challenge_service.join(db, current_user, body)


@router.post("/{challenge_id}/cancel", response_model=ChallengeResponse)
async def cancel_challenge(challenge_id: UUID, db: DBSession, current_user: CurrentUser):
    return await challenge_service.cancel(db, current_user, challenge_id)


@router.post("/{challenge_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_challenge(challenge_id: UUID, db: DBSession, current_user: CurrentUser):
    await challenge_service.leave(db, current_user, challenge_id)


@router.delete("/{challenge_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_challenge_member(challenge_id: UUID, user_id: UUID, db: DBSession, current_user: CurrentUser):
    await challenge_service.remove_member(db, current_user, challenge_id, user_id)
