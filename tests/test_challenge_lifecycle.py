"""When the calendar starts and ends a challenge, as pure arithmetic."""

from datetime import date

from app.challenge.lifecycle import next_status
from app.challenge.models import ChallengeStatus

MONDAY = date(2026, 9, 7)
WEDNESDAY = date(2026, 9, 9)
FRIDAY = date(2026, 9, 11)


def test_a_challenge_stays_pending_until_its_start_date_arrives():
    status = next_status(ChallengeStatus.PENDING, start_date=FRIDAY, end_date=None, member_local_todays=[WEDNESDAY])

    assert status == ChallengeStatus.PENDING


def test_a_challenge_starts_as_soon_as_the_day_arrives_for_anyone():
    # The eastern member is already on Friday while the western one is not.
    status = next_status(
        ChallengeStatus.PENDING, start_date=FRIDAY, end_date=None, member_local_todays=[WEDNESDAY, FRIDAY]
    )

    assert status == ChallengeStatus.ACTIVE


def test_a_challenge_is_only_over_once_its_last_day_closed_for_everyone():
    # Wednesday was the last day: it is gone for one member and still running
    # for the other, who can still upload today's proof.
    still_running = next_status(
        ChallengeStatus.ACTIVE, start_date=MONDAY, end_date=WEDNESDAY, member_local_todays=[WEDNESDAY, FRIDAY]
    )
    over = next_status(
        ChallengeStatus.ACTIVE, start_date=MONDAY, end_date=WEDNESDAY, member_local_todays=[FRIDAY, FRIDAY]
    )

    assert still_running == ChallengeStatus.ACTIVE
    assert over == ChallengeStatus.COMPLETED


def test_an_indefinite_challenge_never_completes_on_its_own():
    status = next_status(ChallengeStatus.ACTIVE, start_date=MONDAY, end_date=None, member_local_todays=[FRIDAY])

    assert status == ChallengeStatus.ACTIVE


def test_a_cancelled_challenge_is_never_revived_by_the_calendar():
    status = next_status(ChallengeStatus.CANCELLED, start_date=MONDAY, end_date=None, member_local_todays=[FRIDAY])

    assert status == ChallengeStatus.CANCELLED


def test_a_completed_challenge_never_reopens():
    status = next_status(ChallengeStatus.COMPLETED, start_date=MONDAY, end_date=None, member_local_todays=[FRIDAY])

    assert status == ChallengeStatus.COMPLETED


def test_a_challenge_without_members_keeps_the_status_it_has():
    status = next_status(ChallengeStatus.PENDING, start_date=MONDAY, end_date=None, member_local_todays=[])

    assert status == ChallengeStatus.PENDING
