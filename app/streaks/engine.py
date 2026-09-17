"""Streak arithmetic: the rules, with no database and no clock of its own.

Streaks are **deduced** from the check-ins, never accumulated by a background
job. Anyone can recompute them at any moment and get the same answer, so a
missed cron run or a server restart cannot leave the scores wrong.

Two ideas drive every rule here:

- **Each member is judged on their own calendar.** Midnight belongs to the
  member, so the same instant is a different date for members in different
  timezones, and a day is only "lost" once *that* member's midnight has passed.
- **Bad news lands immediately, good news waits for everybody.** The group
  streak breaks as soon as the first member's midnight passes with nothing
  uploaded, but it only grows once every member is covered for that day.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum, auto
from uuid import UUID


class DayOutcome(Enum):
    # Covered by an accepted (or still-voting) proof.
    COVERED = auto()
    # The deadline passed with nothing covering it. This is what breaks streaks.
    MISSED = auto()
    # The deadline has not arrived yet, so the day has not decided anything.
    UNDECIDED = auto()


@dataclass(frozen=True)
class MemberFacts:
    """Everything about one member the arithmetic needs."""

    member_id: UUID
    user_id: UUID
    # The member's own today, already resolved in their timezone by the caller:
    # the engine never reads a clock, which is what makes it testable.
    local_today: date
    # The first day this member is answerable for: they cannot miss a day that
    # ran before they joined.
    joined_local_date: date
    # What the late-join policy charged them on the way in.
    inherited_missed_days: int


@dataclass(frozen=True)
class ChallengeFacts:
    start_date: date
    end_date: date | None
    # Weekdays the challenge runs on, Monday = 0.
    active_days: list[int]


@dataclass(frozen=True)
class MemberStreaks:
    current_individual_streak: int
    best_individual_streak: int
    missed_days_count: int


@dataclass(frozen=True)
class StreakResult:
    current_group_streak: int
    best_group_streak: int
    members: dict[UUID, MemberStreaks]


def _active_days_in_range(challenge: ChallengeFacts, last_day: date) -> list[date]:
    days = []
    day = challenge.start_date
    while day <= last_day:
        if day.weekday() in challenge.active_days:
            days.append(day)
        day += timedelta(days=1)
    return days


def _is_answerable(member: MemberFacts, day: date) -> bool:
    return day >= member.joined_local_date


def _member_outcome(member: MemberFacts, day: date, covered: set[tuple[UUID, date]]) -> DayOutcome:
    if (member.user_id, day) in covered:
        return DayOutcome.COVERED
    # Still their day: they can upload until their own midnight.
    if day >= member.local_today:
        return DayOutcome.UNDECIDED
    return DayOutcome.MISSED


def _walk_back(outcomes: list[DayOutcome]) -> int:
    """The run of covered days ending now, ignoring days that are still open."""
    streak = 0
    for outcome in reversed(outcomes):
        if outcome is DayOutcome.UNDECIDED:
            continue
        if outcome is DayOutcome.MISSED:
            break
        streak += 1
    return streak


def _longest_run(outcomes: list[DayOutcome]) -> int:
    best = current = 0
    for outcome in outcomes:
        if outcome is DayOutcome.COVERED:
            current += 1
            best = max(best, current)
        elif outcome is DayOutcome.MISSED:
            current = 0
    return best


def calculate(challenge: ChallengeFacts, members: list[MemberFacts], covered: set[tuple[UUID, date]]) -> StreakResult:
    """Every streak and score for a challenge, from the days its members have lived.

    `covered` holds one entry per (user, day) that has a proof still counting:
    approved, or uploaded and waiting for the group's vote.
    """
    if not members:
        return StreakResult(current_group_streak=0, best_group_streak=0, members={})

    # The calendar runs to the furthest-ahead member: someone in Tokyo is
    # already living a day their partner in Bogotá has not started.
    last_day = max(member.local_today for member in members)
    if challenge.end_date is not None:
        last_day = min(last_day, challenge.end_date)
    days = _active_days_in_range(challenge, last_day)

    member_results: dict[UUID, MemberStreaks] = {}
    for member in members:
        answerable = [day for day in days if _is_answerable(member, day)]
        outcomes = [_member_outcome(member, day, covered) for day in answerable]
        member_results[member.member_id] = MemberStreaks(
            current_individual_streak=_walk_back(outcomes),
            best_individual_streak=_longest_run(outcomes),
            missed_days_count=member.inherited_missed_days
            + sum(1 for outcome in outcomes if outcome is DayOutcome.MISSED),
        )

    group_outcomes = [_group_outcome(members, day, covered) for day in days]

    return StreakResult(
        current_group_streak=_walk_back(group_outcomes),
        best_group_streak=_longest_run(group_outcomes),
        members=member_results,
    )


def _group_outcome(members: list[MemberFacts], day: date, covered: set[tuple[UUID, date]]) -> DayOutcome:
    """One member failing is enough to lose the day for everyone."""
    answerable = [member for member in members if _is_answerable(member, day)]
    if not answerable:
        # Before anyone had joined; nothing to win or lose.
        return DayOutcome.UNDECIDED

    outcomes = [_member_outcome(member, day, covered) for member in answerable]
    if any(outcome is DayOutcome.MISSED for outcome in outcomes):
        return DayOutcome.MISSED
    if all(outcome is DayOutcome.COVERED for outcome in outcomes):
        return DayOutcome.COVERED
    return DayOutcome.UNDECIDED
