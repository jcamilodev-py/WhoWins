import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from app.common.base import Base


class Visibility(enum.StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class DurationType(enum.StrEnum):
    DAYS_10 = "DAYS_10"
    DAYS_20 = "DAYS_20"
    DAYS_30 = "DAYS_30"
    INDEFINITE = "INDEFINITE"


class ChallengeStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LateJoinPolicy(enum.StrEnum):
    CLEAN = "CLEAN"
    INHERIT_MISSED = "INHERIT_MISSED"
    CLOSED = "CLOSED"


class MemberRole(enum.StrEnum):
    CREATOR = "CREATOR"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)

    title: Mapped[str] = mapped_column(String(120), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500))

    # Every challenge has one, public or private; public only adds the option of
    # joining without it.
    invite_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, native_enum=True, length=20), nullable=False, default=Visibility.PRIVATE
    )

    duration_type: Mapped[DurationType] = mapped_column(Enum(DurationType, native_enum=True, length=20), nullable=False)

    # Both null when duration_type is INDEFINITE.
    total_days: Mapped[int | None] = mapped_column(Integer)
    end_date: Mapped[date | None] = mapped_column(Date)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Weekdays the challenge runs on, Monday = 0. Days outside this list need no
    # check-in and never break a streak.
    active_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=lambda: list(range(7)))

    # False means photos are accepted on upload; True sends them to peer review.
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Only consulted once start_date has passed: before that, joining is never late.
    late_join_policy: Mapped[LateJoinPolicy] = mapped_column(
        Enum(LateJoinPolicy, native_enum=True, length=20), nullable=False, default=LateJoinPolicy.CLEAN
    )

    status: Mapped[ChallengeStatus] = mapped_column(
        Enum(ChallengeStatus, native_enum=True, length=20), nullable=False, default=ChallengeStatus.PENDING
    )

    current_group_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_group_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChallengeMember(Base):
    __tablename__ = "challenge_members"

    __table_args__ = (UniqueConstraint("challenge_id", "user_id", name="uq_challenge_member_user"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)

    challenge_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, native_enum=True, length=20), nullable=False, default=MemberRole.MEMBER
    )

    current_individual_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_individual_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The whole score, recomputed from the check-ins: inherited days plus every
    # active day this member let pass without an accepted proof.
    missed_days_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # What INHERIT_MISSED charged at join time. Kept apart from the total because
    # it is a decision taken once, not something the check-ins can re-derive
    # later if the challenge's policy is ever edited.
    inherited_missed_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
