import enum
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from app.common.base import Base

PHOTO_KEY_MAX_LENGTH = 255
REVIEW_COMMENT_MAX_LENGTH = 300


class CheckInStatus(enum.StrEnum):
    # Waiting for peer review. Counts as completed meanwhile: the member did
    # their part on time, and the group's delay must not cost them the day.
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CheckIn(Base):
    __tablename__ = "check_ins"

    # Reads are always "this member's proofs for this challenge on this day".
    # Not unique: several photos a day are allowed, and one accepted one is enough.
    __table_args__ = (Index("ix_check_in_challenge_user_date", "challenge_id", "user_id", "local_date"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)

    challenge_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The calendar day this proof is for, in the author's own timezone. Stored
    # rather than derived from submitted_at: the member's timezone can change,
    # and which day a photo belongs to must not change with it.
    local_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Object storage key, like users.avatar_key: never a URL.
    photo_key: Mapped[str] = mapped_column(String(PHOTO_KEY_MAX_LENGTH), nullable=False)

    status: Mapped[CheckInStatus] = mapped_column(
        Enum(CheckInStatus, native_enum=True, length=20), nullable=False, default=CheckInStatus.PENDING_REVIEW
    )

    # When voting closes: the end of the day after local_date, in the author's
    # timezone, as an absolute instant. Stored so the window never shifts if the
    # member later moves timezone, and so it can be compared in SQL.
    # Null when the challenge auto-approves: there is nothing to vote on.
    review_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Set when the votes settle it; stays null for a proof approved by the
    # window simply running out.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CheckInReview(Base):
    __tablename__ = "check_in_reviews"

    # One vote per reviewer per proof; the vote can be changed while the window
    # is open, which is an update of this row rather than a second one.
    __table_args__ = (UniqueConstraint("check_in_id", "reviewer_id", name="uq_check_in_review_reviewer"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)

    check_in_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("check_ins.id", ondelete="CASCADE"), nullable=False, index=True
    )

    reviewer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False)

    comment: Mapped[str | None] = mapped_column(String(REVIEW_COMMENT_MAX_LENGTH))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
