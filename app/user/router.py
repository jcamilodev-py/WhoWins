from uuid import UUID

from fastapi import APIRouter

from app.auth.dependencies import CurrentUser, RequireRoleAdmin
from app.core.database import DBSession
from app.user.schemas import UserResponse, UserUpdateMe
from app.user import service as user_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return user_service._to_response(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(data: UserUpdateMe, db: DBSession, current_user: CurrentUser):
    return await user_service.update_me(db, current_user, data)


@router.get("/{user_id}", response_model=UserResponse)
async def get_by_id(user_id: UUID, db: DBSession, _admin: RequireRoleAdmin):
    return await user_service.find_by_id(db, user_id)


@router.get("/email/{email}", response_model=UserResponse)
async def get_by_email(db: DBSession, email: str, _admin: RequireRoleAdmin):
    return await user_service.find_by_email(db, email)


@router.get("/google_id/{google_id}", response_model=UserResponse)
async def get_by_google_id(db: DBSession, google_id: str, _admin: RequireRoleAdmin):
    return await user_service.find_by_google_id(db, google_id)


@router.get("/exists/{email}", response_model=bool)
async def exists_by_email(db: DBSession, email: str, _admin: RequireRoleAdmin):
    return await user_service.exists_by_email(db, email)
