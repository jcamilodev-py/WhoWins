from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from pydantic.alias_generators import to_camel

from app.user.models import AVATAR_KEY_MAX_LENGTH, DISPLAY_NAME_MAX_LENGTH, AuthProvider, Role

# Stripping runs before the length check, so a name of only spaces is rejected.
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)]


def _validate_timezone(value: str) -> str:
    if value not in available_timezones():
        raise ValueError("Invalid IANA timezone identifier.")
    return value


# Every deadline in WhoWins is local to the member, so a wrong timezone silently
# moves their midnight. Validated wherever it is accepted, never only on update.
Timezone = Annotated[str, AfterValidator(_validate_timezone)]


class UserResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None
    # A short-lived signed URL, rebuilt on every response: the stored value is a
    # key, and the photo is never public. Null when the user has no photo.
    avatar_url: str | None = None
    role: Role
    auth_provider: AuthProvider
    timezone: str
    active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


class UserUpdateMe(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    display_name: DisplayName | None = None
    timezone: Timezone | None = None


class AvatarUploadRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Checked against the allowed types in the service, which reads the setting.
    content_type: str = Field(..., description="Image content type is required")


class AvatarUploadResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    upload_url: str
    key: str
    # The client must send this exact Content-Type header: it is part of the signature.
    content_type: str
    expires_in_seconds: int
    max_bytes: int


class AvatarConfirmRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    key: Annotated[str, StringConstraints(min_length=1, max_length=AVATAR_KEY_MAX_LENGTH)] = Field(
        ..., description="The key returned by the upload URL request"
    )
