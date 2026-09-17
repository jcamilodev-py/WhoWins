"""The streak rules, tested as pure arithmetic.

No database and no clock: every "today" is passed in, so a test that says
"someone missed yesterday" means exactly that, whatever time the suite runs at.
"""

import uuid
from datetime import date

from app.streaks.engine import ChallengeFacts, MemberFacts, calculate

MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)
WEDNESDAY = date(2026, 9, 9)
THURSDAY = date(2026, 9, 10)
FRIDAY = date(2026, 9, 11)
SATURDAY = date(2026, 9, 12)

EVERY_DAY = list(range(7))
WEEKDAYS = [0, 1, 2, 3, 4]


def _member(local_today: date, joined: date = MONDAY, inherited: int = 0) -> MemberFacts:
    identifier = uuid.uuid4()
    return MemberFacts(
        member_id=identifier,
        user_id=identifier,
        local_today=local_today,
        joined_local_date=joined,
        inherited_missed_days=inherited,
    )


def _challenge(start: date = MONDAY, end: date | None = None, active_days=EVERY_DAY) -> ChallengeFacts:
    return ChallengeFacts(start_date=start, end_date=end, active_days=active_days)


def _covered(*pairs: tuple[MemberFacts, date]) -> set[tuple[uuid.UUID, date]]:
    return {(member.user_id, day) for member, day in pairs}


# --- a single member ---


def test_a_challenge_that_has_not_started_scores_nothing():
    member = _member(local_today=MONDAY, joined=MONDAY)

    result = calculate(_challenge(start=FRIDAY), [member], set())

    assert result.current_group_streak == 0
    assert result.members[member.member_id].missed_days_count == 0


def test_today_alone_is_not_a_missed_day_until_midnight_passes():
    member = _member(local_today=TUESDAY)

    result = calculate(_challenge(), [member], set())

    # Monday was missed, Tuesday is still open.
    assert result.members[member.member_id].missed_days_count == 1
    assert result.members[member.member_id].current_individual_streak == 0


def test_covering_today_counts_immediately():
    member = _member(local_today=TUESDAY)

    result = calculate(_challenge(), [member], _covered((member, MONDAY), (member, TUESDAY)))

    assert result.members[member.member_id].current_individual_streak == 2
    assert result.members[member.member_id].missed_days_count == 0


def test_a_missed_day_breaks_the_streak_but_keeps_the_record():
    member = _member(local_today=FRIDAY)

    result = calculate(
        _challenge(),
        [member],
        _covered((member, MONDAY), (member, TUESDAY), (member, WEDNESDAY), (member, FRIDAY)),
    )

    streaks = result.members[member.member_id]
    # Thursday was missed, so the current run is only Friday.
    assert streaks.current_individual_streak == 1
    assert streaks.best_individual_streak == 3
    assert streaks.missed_days_count == 1


def test_rest_days_neither_break_a_streak_nor_count_as_missed():
    member = _member(local_today=date(2026, 9, 14), joined=MONDAY)  # the next Monday

    # Only weekdays are active, and the member covered every one of them.
    result = calculate(
        _challenge(active_days=WEEKDAYS),
        [member],
        _covered(*[(member, day) for day in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY)]),
    )

    streaks = result.members[member.member_id]
    assert streaks.missed_days_count == 0
    # The weekend is skipped entirely, so the run survives it.
    assert streaks.current_individual_streak == 5


def test_days_before_joining_are_not_charged():
    member = _member(local_today=THURSDAY, joined=WEDNESDAY)

    result = calculate(_challenge(), [member], _covered((member, WEDNESDAY)))

    # Monday and Tuesday ran before this member existed in the challenge.
    assert result.members[member.member_id].missed_days_count == 0


def test_inherited_days_are_added_to_what_the_member_missed_afterwards():
    member = _member(local_today=WEDNESDAY, joined=TUESDAY, inherited=4)

    result = calculate(_challenge(), [member], set())

    # Four charged on the way in, plus Tuesday let slip.
    assert result.members[member.member_id].missed_days_count == 5


def test_nothing_is_counted_after_the_challenge_ends():
    member = _member(local_today=SATURDAY)

    result = calculate(
        _challenge(end=TUESDAY),
        [member],
        _covered((member, MONDAY), (member, TUESDAY)),
    )

    assert result.members[member.member_id].missed_days_count == 0
    assert result.members[member.member_id].current_individual_streak == 2


# --- the group ---


def test_the_group_streak_grows_only_when_everyone_is_covered():
    ana = _member(local_today=TUESDAY)
    bob = _member(local_today=TUESDAY)

    only_ana = calculate(_challenge(), [ana, bob], _covered((ana, MONDAY), (ana, TUESDAY)))
    both = calculate(_challenge(), [ana, bob], _covered((ana, MONDAY), (bob, MONDAY), (ana, TUESDAY), (bob, TUESDAY)))

    # Bob let Monday pass, so the group lost it even though Ana did her part.
    assert only_ana.current_group_streak == 0
    assert both.current_group_streak == 2


def test_one_member_failing_breaks_the_streak_for_everyone():
    ana = _member(local_today=WEDNESDAY)
    bob = _member(local_today=WEDNESDAY)
    covered = _covered((ana, MONDAY), (bob, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (bob, WEDNESDAY))

    result = calculate(_challenge(), [ana, bob], covered)

    # Monday was perfect, Tuesday was Bob's miss, Wednesday is covered by both.
    assert result.current_group_streak == 1
    assert result.best_group_streak == 1
    assert result.members[ana.member_id].current_individual_streak == 3
    assert result.members[bob.member_id].current_individual_streak == 1


def test_a_day_still_open_for_someone_does_not_grow_the_group_streak():
    # Ana is already on Tuesday; Bob is still living Monday.
    ana = _member(local_today=TUESDAY)
    bob = _member(local_today=MONDAY)

    result = calculate(_challenge(), [ana, bob], _covered((ana, MONDAY)))

    # Monday cannot be claimed yet: Bob still has until his own midnight.
    assert result.current_group_streak == 0
    assert result.members[bob.member_id].missed_days_count == 0


def test_the_group_streak_breaks_at_the_first_midnight_that_passes_with_a_miss():
    # Same instant: Ana has already crossed into Tuesday without uploading,
    # while Bob is still on Monday and covered.
    ana = _member(local_today=TUESDAY)
    bob = _member(local_today=MONDAY)

    result = calculate(_challenge(), [ana, bob], _covered((bob, MONDAY)))

    # Bad news does not wait for Bob's midnight.
    assert result.current_group_streak == 0
    assert result.members[ana.member_id].missed_days_count == 1


def test_a_member_who_joins_late_does_not_erase_the_group_history():
    ana = _member(local_today=WEDNESDAY)
    bob = _member(local_today=WEDNESDAY, joined=WEDNESDAY)
    covered = _covered((ana, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (bob, WEDNESDAY))

    result = calculate(_challenge(), [ana, bob], covered)

    # Bob was not there on Monday or Tuesday, so those days still count for the group.
    assert result.current_group_streak == 3


def test_a_challenge_without_members_scores_nothing():
    result = calculate(_challenge(), [], set())

    assert result.current_group_streak == 0
    assert result.members == {}
