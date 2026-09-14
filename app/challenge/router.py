from fastapi import APIRouter, Request, status

from app.auth.dependencies import CurrentUser
from app.challenge.repository import ChallengeMemberRepository, ChallengeRepository
from app.challenge.schemas import ChallengeCreate, ChallengeResponse, JoinChallengeRequest
from app.challenge.service import ChallengeService
from app.core.database import DBSession
from app.core.limiter import limiter

router = APIRouter(prefix="/api/v1/challenges", tags=["challenges"])

challenge_service = ChallengeService(ChallengeRepository(), ChallengeMemberRepository())


@router.post("", response_model=ChallengeResponse, status_code=status.HTTP_201_CREATED)
async def create_challenge(body: ChallengeCreate, db: DBSession, current_user: CurrentUser):
    return await challenge_service.create(db, current_user, body)


@router.post("/join", response_model=ChallengeResponse)
# Private challenges are only as private as their code is hard to guess.
@limiter.limit("10/minute")
async def join_challenge(request: Request, body: JoinChallengeRequest, db: DBSession, current_user: CurrentUser):
    return await challenge_service.join(db, current_user, body)
