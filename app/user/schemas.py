from datetime import datetime
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from pydantic.alias_generators import to_camel

from app.user.models import AuthProvider, Role


class UserResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: UUID
    email: EmailStr
    role: Role
    auth_provider: AuthProvider
    timezone: str
    active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


class UserUpdateMe(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        if v is not None and v not in available_timezones():
            raise ValueError("Invalid IANA timezone identifier.")
        return v