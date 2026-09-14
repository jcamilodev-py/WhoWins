from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic.alias_generators import to_camel

from app.challenge.models import ChallengeStatus, DurationType, LateJoinPolicy, MemberRole, Visibility


class ChallengeCreate(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Not accepted from the client: invite_code is generated, total_days and
    # end_date are derived from duration_type, and streaks/status start fixed.
    title: str = Field(..., min_length=1, max_length=120, description="Challenge title is required")
    description: str | None = Field(None, max_length=500)
    duration_type: DurationType
    start_date: date
    active_days: list[int] = Field(default_factory=lambda: list(range(7)))
    visibility: Visibility = Visibility.PRIVATE
    requires_approval: bool = False
    late_join_policy: LateJoinPolicy = LateJoinPolicy.CLEAN

    @field_validator("active_days")
    @classmethod
    def validate_active_days(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("At least one active day is required.")
        if len(set(value)) != len(value):
            raise ValueError("Active days must not repeat.")
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Active days must be between 0 (Monday) and 6 (Sunday).")
        return sorted(value)


class JoinChallengeRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Codes are typed by hand on phones, so casing and stray spaces must not
    # turn a correct code into "not found". Stripping runs before the length check.
    invite_code: Annotated[
        str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)
    ] = Field(..., description="Invite code is required")


class ChallengeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: UUID
    title: str
    description: str | None
    invite_code: str
    visibility: Visibility
    duration_type: DurationType
    total_days: int | None
    start_date: date
    end_date: date | None
    active_days: list[int]
    requires_approval: bool
    late_join_policy: LateJoinPolicy
    status: ChallengeStatus
    current_group_streak: int
    best_group_streak: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ChallengeMemberResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    id: UUID
    challenge_id: UUID
    user_id: UUID
    role: MemberRole
    current_individual_streak: int
    best_individual_streak: int
    missed_days_count: int
    joined_at: datetime


class MyChallengeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    challenge: ChallengeResponse
    my_membership: ChallengeMemberResponse
    member_count: int


class LeaderboardEntryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Members with equal missed days share a rank (1, 1, 3) until a tie-breaker exists.
    # No email on purpose: anyone holding the invite code can see this list.
    rank: int
    user_id: UUID
    role: MemberRole
    current_individual_streak: int
    best_individual_streak: int
    missed_days_count: int
    joined_at: datetime


class ChallengeDetailResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    challenge: ChallengeResponse
    leaderboard: list[LeaderboardEntryResponse]
