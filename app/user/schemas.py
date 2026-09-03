from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr
from pydantic.alias_generators import to_camel

from app.user.models import AuthProvider, Role


class UserResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: UUID
    email: EmailStr
    role: Role
    auth_provider: AuthProvider
    active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime