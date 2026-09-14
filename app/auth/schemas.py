import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from app.user.models import Role
from app.user.schemas import DisplayName


class RegisterRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # El rol NO se acepta del cliente: siempre se crea como Role.USER.
    # Promover a ADMIN es una operacion administrativa aparte.
    email: EmailStr = Field(..., description="Email is required")
    password: str = Field(..., min_length=8, description="Password is required")
    display_name: DisplayName = Field(..., description="Display name is required")


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    email: EmailStr = Field(..., description="email is required")


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    token: str = Field(..., min_length=1, description="token is required")
    new_password: str = Field(..., min_length=8, description="new password is required")


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    current_password: str = Field(..., min_length=1, description="current password is required")
    new_password: str = Field(..., min_length=8, description="new password is required")


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, alias_generator=to_camel, populate_by_name=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None
    role: Role


class AuthResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    access_token: str
    token_type: str = "bearer"
    user: UserPublic
