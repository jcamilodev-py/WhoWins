from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from app.checkin.models import PHOTO_KEY_MAX_LENGTH, REVIEW_COMMENT_MAX_LENGTH, CheckInStatus


class DayStatus(StrEnum):
    # Not an active day for that member: nothing is owed and nothing breaks.
    REST_DAY = "REST_DAY"
    # Owed today and not covered yet, either because nothing was uploaded or
    # because everything uploaded was rejected.
    MISSING = "MISSING"
    # Uploaded and waiting for the group's vote. Counts as done meanwhile.
    AWAITING_REVIEW = "AWAITING_REVIEW"
    DONE = "DONE"


class CheckInUploadRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    content_type: str = Field(..., description="Image content type is required")


class CheckInUploadResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    upload_url: str
    key: str
    # The client must send this exact Content-Type header: it is part of the signature.
    content_type: str
    expires_in_seconds: int
    max_bytes: int
    # The day this proof will count for, in the member's own timezone.
    local_date: date


class CheckInConfirmRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    key: Annotated[str, StringConstraints(min_length=1, max_length=PHOTO_KEY_MAX_LENGTH)] = Field(
        ..., description="The key returned by the upload URL request"
    )


class CheckInResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    challenge_id: UUID
    user_id: UUID
    local_date: date
    status: CheckInStatus
    # When voting closes; null when the challenge approves photos on upload.
    review_closes_at: datetime | None
    submitted_at: datetime
    # Signed and short-lived, like avatarUrl: photos are never public.
    photo_url: str


class MemberDayStatusResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: UUID
    display_name: str | None
    # Each member is judged by their own calendar: midnight is local to them,
    # so two members can be on different dates at the same instant.
    local_date: date
    is_active_day: bool
    status: DayStatus
    check_in_id: UUID | None
    photo_url: str | None
    submitted_at: datetime | None


class TodayStatusResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    challenge_id: UUID
    viewer_local_date: date
    members: list[MemberDayStatusResponse]


class ReviewVoteRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    is_approved: bool = Field(..., description="Whether the proof is accepted")
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=REVIEW_COMMENT_MAX_LENGTH)] | None = (
        None
    )


class CheckInUnderReviewResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    challenge_id: UUID
    # The author. Their own proof is never theirs to vote on.
    user_id: UUID
    display_name: str | None
    local_date: date
    photo_url: str
    status: CheckInStatus
    review_closes_at: datetime | None
    submitted_at: datetime
    approvals: int
    rejections: int
    # Members other than the author; the majority is counted over these.
    eligible_reviewers: int
    # What the caller voted, or null if they have not voted yet.
    my_vote: bool | None
