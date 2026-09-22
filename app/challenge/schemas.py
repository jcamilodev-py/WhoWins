from datetime import date, datetime
from enum import StrEnum
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
    cancelled_at: datetime | None
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
    # Null for accounts that have not set a name yet; clients show a fallback.
    display_name: str | None
    # Signed and short-lived like every photo URL; null means show initials.
    avatar_url: str | None = None
    role: MemberRole
    current_individual_streak: int
    best_individual_streak: int
    missed_days_count: int
    joined_at: datetime


class GroupBreakMemberResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: UUID
    display_name: str | None
    avatar_url: str | None


class GroupBreakResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # The most recent day the group lost, and who let it slip. Naming them is a
    # product decision: the social pressure is the point. Called "day" rather
    # than "date" so the field does not shadow the type it is declared with.
    day: date
    members: list[GroupBreakMemberResponse]


class ChallengeDetailResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    challenge: ChallengeResponse
    leaderboard: list[LeaderboardEntryResponse]
    # Null while the group has never lost a day.
    last_group_break: GroupBreakResponse | None = None


class HistoryOutcome(StrEnum):
    COVERED = "COVERED"
    MISSED = "MISSED"
    # Not decided yet: still today for that member, or not reached yet.
    OPEN = "OPEN"
    # Not an active day of the challenge.
    REST_DAY = "REST_DAY"
    # An active day that ran before this member joined; nothing was owed.
    NOT_JOINED = "NOT_JOINED"
    # An active day from the day this member left onwards.
    LEFT = "LEFT"


class HistoryDayResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    day: date
    outcome: HistoryOutcome


class MemberHistoryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: UUID
    display_name: str | None
    # Null while they are still in the challenge.
    left_at: datetime | None
    # True when the creator removed them, false when they left on their own.
    removed: bool
    days: list[HistoryDayResponse]


class ChallengeHistoryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    challenge_id: UUID
    # Every calendar day covered by the response, oldest first, rest days included.
    dates: list[date]
    members: list[MemberHistoryResponse]


class JoinStatus(StrEnum):
    OPEN = "OPEN"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    # Started, and the late-join policy is CLOSED.
    CLOSED = "CLOSED"
    # Completed, cancelled, or past its end date.
    FINISHED = "FINISHED"
    # The caller was in it and left or was removed; there is no way back in.
    LEFT = "LEFT"


class ChallengePreviewResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Only what someone needs to decide whether to join. The leaderboard and the
    # other members' names stay members-only; the stored status is left out because
    # it can be stale, and join_status already answers the question it would.
    id: UUID
    title: str
    description: str | None
    duration_type: DurationType
    total_days: int | None
    start_date: date
    end_date: date | None
    active_days: list[int]
    requires_approval: bool
    late_join_policy: LateJoinPolicy
    member_count: int
    creator_display_name: str | None
    join_status: JoinStatus
    # Null unless join_status is OPEN.
    missed_days_on_join: int | None
