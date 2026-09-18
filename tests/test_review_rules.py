"""The voting rules, as pure arithmetic.

Every case the product decided, stated as a tally: how many approved, how many
rejected, and how many members were allowed to vote at all.
"""

import pytest

from app.checkin.models import CheckInStatus
from app.checkin.review_rules import decide


@pytest.mark.parametrize(
    ("approvals", "rejections", "eligible", "expected"),
    [
        # A couple: the single reviewer decides alone, either way.
        pytest.param(1, 0, 1, CheckInStatus.APPROVED, id="partner-approves"),
        pytest.param(0, 1, 1, CheckInStatus.REJECTED, id="partner-rejects"),
        pytest.param(0, 0, 1, None, id="partner-has-not-voted"),
        # Two reviewers: one vote is not a majority, and a tie approves.
        pytest.param(1, 0, 2, None, id="one-of-two-approves"),
        pytest.param(0, 1, 2, None, id="one-of-two-rejects"),
        pytest.param(1, 1, 2, CheckInStatus.APPROVED, id="two-way-tie-approves"),
        pytest.param(2, 0, 2, CheckInStatus.APPROVED, id="both-approve"),
        pytest.param(0, 2, 2, CheckInStatus.REJECTED, id="both-reject"),
        # Three reviewers: two votes settle it before the third answers.
        pytest.param(2, 0, 3, CheckInStatus.APPROVED, id="two-of-three-approve"),
        pytest.param(0, 2, 3, CheckInStatus.REJECTED, id="two-of-three-reject"),
        pytest.param(1, 1, 3, None, id="three-way-still-open"),
        # Four reviewers: an even split approves once everyone has voted.
        pytest.param(2, 2, 4, CheckInStatus.APPROVED, id="four-way-tie-approves"),
        pytest.param(3, 1, 4, CheckInStatus.APPROVED, id="three-of-four-approve"),
        pytest.param(1, 3, 4, CheckInStatus.REJECTED, id="three-of-four-reject"),
    ],
)
def test_the_majority_decides(approvals: int, rejections: int, eligible: int, expected: CheckInStatus | None):
    assert decide(approvals, rejections, eligible) == expected


def test_a_member_alone_in_a_challenge_can_never_be_voted_on():
    # There is nobody else to vote, so only the closing window settles it.
    assert decide(0, 0, 0) is None
