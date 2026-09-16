from uuid import UUID

from fastapi import APIRouter, Request

from app.auth.dependencies import CurrentUser, RequireRoleAdmin
from app.core.database import DBSession
from app.core.limiter import limiter
from app.user import service as user_service
from app.user.schemas import (
    AvatarConfirmRequest,
    AvatarUploadRequest,
    AvatarUploadResponse,
    UserResponse,
    UserUpdateMe,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return user_service._to_response(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(data: UserUpdateMe, db: DBSession, current_user: CurrentUser):
    return await user_service.update_me(db, current_user, data)


@router.post("/me/avatar/upload-url", response_model=AvatarUploadResponse)
# Signing is cheap, but each URL is a write permission on the bucket for five minutes.
@limiter.limit("10/minute")
async def create_avatar_upload_url(request: Request, body: AvatarUploadRequest, current_user: CurrentUser):
    return user_service.create_avatar_upload(current_user, body)


@router.put("/me/avatar", response_model=UserResponse)
async def confirm_avatar(body: AvatarConfirmRequest, db: DBSession, current_user: CurrentUser):
    return await user_service.confirm_avatar(db, current_user, body)


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_avatar(db: DBSession, current_user: CurrentUser):
    return await user_service.delete_avatar(db, current_user)


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
