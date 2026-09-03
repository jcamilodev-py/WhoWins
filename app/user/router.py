from uuid import UUID

from fastapi import APIRouter

from app.auth.dependencies import RequireRoleAdmin
from app.core.database import DBSession
from app.user.schemas import UserResponse
from app.user import service as user_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/{id}", response_model=UserResponse)
async def get_by_id(id: UUID, db: DBSession, _admin: RequireRoleAdmin):
    return await user_service.find_by_id(db, id)


@router.get("/{email}", response_model=UserResponse)
async def get_by_email(db: DBSession, email: str, _admin: RequireRoleAdmin):
    return await user_service.find_by_email(db, email)


@router.get("/{google_id}", response_model=UserResponse)
async def get_by_google_id(db: DBSession, google_id: str, _admin: RequireRoleAdmin):
    return await user_service.find_by_google_id(db, google_id)


@router.get("/{reset_token}", response_model=UserResponse)
async def get_by_reset_token(db: DBSession, reset_token: str, _admin: RequireRoleAdmin):
    return await user_service.find_by_reset_token(db, reset_token)


@router.get("/exists/{email}", response_model=bool)
async def exists_by_email(db: DBSession, email: str, _admin: RequireRoleAdmin):
    return await user_service.exists_by_email(db, email)