import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.core.settings import settings
from app.shared.exception.errors import BusinessException, ResourceNotFoundException
from app.shared.storage.object_storage import ObjectStorageError, object_storage
from app.user.models import User
from app.user.repository import UserRepository
from app.user.schemas import AvatarConfirmRequest, AvatarUploadRequest, AvatarUploadResponse, UserResponse, UserUpdateMe

logger = logging.getLogger(__name__)

user_repository = UserRepository()

# Only formats every browser can display. The extension is cosmetic: the stored
# content type is what matters.
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _to_response(user: User) -> UserResponse:
    response = UserResponse.model_validate(user)
    if user.avatar_key is not None:
        # Signed per response: the URL expires, so it cannot be shared forever.
        response.avatar_url = object_storage.create_download_url(user.avatar_key)
    return response


def _avatar_prefix(user: User) -> str:
    return f"users/{user.id}/avatar/"


def _normalize_content_type(content_type: str) -> str:
    normalized = content_type.split(";")[0].strip().lower()
    if normalized not in settings.allowed_image_types or normalized not in IMAGE_EXTENSIONS:
        raise BusinessException(f"Unsupported image type: {content_type}.")
    return normalized


def create_avatar_upload(user: User, data: AvatarUploadRequest) -> AvatarUploadResponse:
    content_type = _normalize_content_type(data.content_type)
    # A fresh key per upload: overwriting one key would leave every cached copy
    # and every still-valid signed URL pointing at the old photo.
    key = f"{_avatar_prefix(user)}{uuid7().hex}.{IMAGE_EXTENSIONS[content_type]}"
    upload = object_storage.create_upload_url(key, content_type)
    return AvatarUploadResponse(
        upload_url=upload.url,
        key=upload.key,
        content_type=upload.content_type,
        expires_in_seconds=upload.expires_in_seconds,
        max_bytes=settings.storage_max_upload_bytes,
    )


async def confirm_avatar(db: AsyncSession, user: User, data: AvatarConfirmRequest) -> UserResponse:
    """Adopts an uploaded object as the user's photo, once it is known to be one."""
    # The client chooses which key to confirm, so it could name someone else's
    # object. Only keys under this user's own prefix are accepted.
    if not data.key.startswith(_avatar_prefix(user)):
        raise BusinessException("This upload does not belong to the current user.")

    stored = await object_storage.stat(data.key)
    if stored is None:
        raise BusinessException("The upload was not found. Request a new upload URL and try again.")

    # A presigned PUT cannot cap the size, so an oversized file is rejected and
    # removed here rather than left paid for and unreferenced.
    if stored.size_bytes > settings.storage_max_upload_bytes:
        await object_storage.delete(data.key)
        raise BusinessException(f"The image is larger than {settings.storage_max_upload_bytes} bytes.")
    if stored.content_type.split(";")[0].strip().lower() not in settings.allowed_image_types:
        await object_storage.delete(data.key)
        raise BusinessException(f"Unsupported image type: {stored.content_type}.")

    previous_key = user.avatar_key
    user.avatar_key = data.key
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await _delete_replaced_avatar(previous_key, data.key)
    return _to_response(user)


async def delete_avatar(db: AsyncSession, user: User) -> UserResponse:
    previous_key = user.avatar_key
    user.avatar_key = None
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await _delete_replaced_avatar(previous_key, None)
    return _to_response(user)


async def _delete_replaced_avatar(previous_key: str | None, current_key: str | None) -> None:
    """Deletes the photo that was just replaced.

    Best effort on purpose: the new photo is already saved, so a storage hiccup
    here must not fail the request. The worst case is one orphaned file.
    """
    if previous_key is None or previous_key == current_key:
        return
    try:
        await object_storage.delete(previous_key)
    except ObjectStorageError:
        logger.warning("Could not delete the replaced avatar %s", previous_key)


async def update_me(db: AsyncSession, user: User, data: UserUpdateMe) -> UserResponse:
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.timezone is not None:
        user.timezone = data.timezone
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _to_response(user)


async def find_by_id(db: AsyncSession, user_id: UUID) -> UserResponse:
    user = await user_repository.find_by_id(db, user_id)
    if user is None:
        raise ResourceNotFoundException("User", "id", user_id)

    return _to_response(user)


async def find_by_email(db: AsyncSession, email: str) -> UserResponse:
    user = await user_repository.find_by_email(db, email)
    if user is None:
        raise ResourceNotFoundException("User", "email", email)

    return _to_response(user)


async def find_by_google_id(db: AsyncSession, google_id: str) -> UserResponse:
    user = await user_repository.find_by_google_id(db, google_id)
    if user is None:
        raise ResourceNotFoundException("User", "google id", google_id)

    return _to_response(user)


async def exists_by_email(db: AsyncSession, email: str) -> bool:
    return await user_repository.exists_by_email(db, email)
