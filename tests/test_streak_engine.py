"""The streak rules, tested as pure arithmetic.

No database and no clock: every "today" is passed in, so a test that says
"someone missed yesterday" means exactly that, whatever time the suite runs at.
"""

import uuid
from datetime import date

from app.streaks.engine import ChallengeFacts, DayOutcome, MemberFacts, calculate

MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)
WEDNESDAY = date(2026, 9, 9)
THURSDAY = date(2026, 9, 10)
FRIDAY = date(2026, 9, 11)
SATURDAY = date(2026, 9, 12)

EVERY_DAY = list(range(7))
WEEKDAYS = [0, 1, 2, 3, 4]


def _member(local_today: date, joined: date = MONDAY, inherited: int = 0, left: date | None = None) -> MemberFacts:
    identifier = uuid.uuid4()
    return MemberFacts(
        member_id=identifier,
        user_id=identifier,
        local_today=local_today,
        joined_local_date=joined,
        inherited_missed_days=inherited,
        left_local_date=left,
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


# --- who broke it ---


def test_a_group_that_never_lost_a_day_has_no_break():
    ana = _member(local_today=TUESDAY)

    result = calculate(_challenge(), [ana], _covered((ana, MONDAY), (ana, TUESDAY)))

    assert result.last_group_break is None


def test_the_break_names_the_member_who_let_the_day_slip():
    ana = _member(local_today=WEDNESDAY)
    bob = _member(local_today=WEDNESDAY)
    covered = _covered((ana, MONDAY), (bob, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (bob, WEDNESDAY))

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.last_group_break is not None
    assert result.last_group_break.day == TUESDAY
    assert result.last_group_break.user_ids == [bob.user_id]


def test_the_break_is_the_most_recent_one():
    ana = _member(local_today=FRIDAY)
    bob = _member(local_today=FRIDAY)
    # Bob missed Tuesday, then Ana missed Thursday.
    covered = _covered(
        (ana, MONDAY), (bob, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (bob, WEDNESDAY), (bob, THURSDAY)
    )

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.last_group_break is not None
    assert result.last_group_break.day == THURSDAY
    assert result.last_group_break.user_ids == [ana.user_id]


def test_everyone_who_missed_the_same_day_is_named():
    ana = _member(local_today=TUESDAY)
    bob = _member(local_today=TUESDAY)

    result = calculate(_challenge(), [ana, bob], set())

    assert result.last_group_break is not None
    assert set(result.last_group_break.user_ids) == {ana.user_id, bob.user_id}


def test_a_day_still_running_is_not_a_break_yet():
    ana = _member(local_today=MONDAY)

    result = calculate(_challenge(), [ana], set())

    # Ana can still upload before her midnight: nothing is broken.
    assert result.last_group_break is None


# --- day by day ---


def test_each_member_carries_the_outcome_of_every_day_they_answered_for():
    ana = _member(local_today=WEDNESDAY, joined=TUESDAY)

    result = calculate(_challenge(), [ana], _covered((ana, TUESDAY)))

    assert result.members[ana.member_id].days == {
        TUESDAY: DayOutcome.COVERED,
        WEDNESDAY: DayOutcome.UNDECIDED,
    }


# --- leaving ---


def test_a_member_is_not_charged_from_the_day_they_leave():
    bob = _member(local_today=FRIDAY, left=WEDNESDAY)

    result = calculate(_challenge(), [bob], _covered((bob, MONDAY)))

    assert result.members[bob.member_id].missed_days_count == 1
    assert result.members[bob.member_id].days == {MONDAY: DayOutcome.COVERED, TUESDAY: DayOutcome.MISSED}


def test_the_group_streak_stops_depending_on_a_member_who_left():
    ana = _member(local_today=FRIDAY)
    bob = _member(local_today=FRIDAY, left=WEDNESDAY)
    covered = _covered(
        (ana, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (ana, THURSDAY), (ana, FRIDAY), (bob, MONDAY), (bob, TUESDAY)
    )

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.current_group_streak == 5


def test_the_day_a_member_leaves_does_not_hold_the_group_back():
    ana = _member(local_today=TUESDAY)
    bob = _member(local_today=TUESDAY, left=TUESDAY)
    covered = _covered((ana, MONDAY), (bob, MONDAY), (ana, TUESDAY))

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.current_group_streak == 2


def test_leaving_does_not_undo_a_break_the_member_already_caused():
    ana = _member(local_today=THURSDAY)
    bob = _member(local_today=THURSDAY, left=WEDNESDAY)
    covered = _covered((ana, MONDAY), (bob, MONDAY), (ana, TUESDAY), (ana, WEDNESDAY), (ana, THURSDAY))

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.current_group_streak == 2
    assert result.last_group_break is not None
    assert result.last_group_break.day == TUESDAY
    assert result.last_group_break.user_ids == [bob.user_id]


def test_a_member_who_left_still_reaches_the_days_they_lived():
    # Bob is a day ahead of Ana: he lived through Friday, missed it, and left on
    # his Saturday while Ana is still on Thursday.
    ana = _member(local_today=THURSDAY)
    bob = _member(local_today=SATURDAY, left=SATURDAY)
    covered = _covered(*((member, day) for member in (ana, bob) for day in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY)))

    result = calculate(_challenge(), [ana, bob], covered)

    assert result.last_day == FRIDAY
    assert result.current_group_streak == 0
    assert result.last_group_break is not None
    assert result.last_group_break.day == FRIDAY
