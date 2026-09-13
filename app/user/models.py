import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from app.common.base import Base


class Role(enum.StrEnum):
    ADMIN = "ADMIN"
    USER = "USER"


class AuthProvider(enum.StrEnum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)

    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)

    password: Mapped[str | None] = mapped_column("password_hash", String(255))

    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=True, length=20), nullable=False, default=Role.USER)

    auth_provider: Mapped[AuthProvider] = mapped_column(Enum(AuthProvider, native_enum=True, length=20), nullable=False)

    google_id: Mapped[str | None] = mapped_column(String(100), unique=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC", server_default="UTC")

    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    reset_token: Mapped[str | None] = mapped_column(String(255), index=True)

    reset_token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
