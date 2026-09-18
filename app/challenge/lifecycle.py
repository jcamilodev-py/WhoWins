"""When a challenge starts and when it is over.

Derived from the dates the same way the streaks are derived from the check-ins:
nothing schedules this, so the answer is computed whenever someone looks.

The two rules are deliberately asymmetric, because midnight belongs to each
member: a challenge is **running** as soon as it has started for anyone, and
**over** only once its last day has closed for everyone. Ending early would take
the final day away from whoever is still living it.
"""

from datetime import date

from app.challenge.models import ChallengeStatus


def next_status(
    current: ChallengeStatus,
    start_date: date,
    end_date: date | None,
    member_local_todays: list[date],
) -> ChallengeStatus:
    """The status the calendar forces, or the current one when nothing moved."""
    # A cancelled challenge was ended by a person, not by the calendar, and a
    # finished one never reopens.
    if current in (ChallengeStatus.CANCELLED, ChallengeStatus.COMPLETED):
        return current
    if not member_local_todays:
        return current

    if end_date is not None and min(member_local_todays) > end_date:
        return ChallengeStatus.COMPLETED
    if max(member_local_todays) >= start_date:
        return ChallengeStatus.ACTIVE
    return ChallengeStatus.PENDING
