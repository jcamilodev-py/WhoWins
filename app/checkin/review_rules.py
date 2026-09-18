"""When the group's votes settle a proof.

Pure arithmetic, like the streak engine: given the tally, it answers what the
rules force. Everything the product decided about peer review lives here.
"""

from app.checkin.models import CheckInStatus


def decide(approvals: int, rejections: int, eligible_reviewers: int) -> CheckInStatus | None:
    """The status the votes force, or None while the proof is still undecided.

    The majority is counted over the members **other than the author**: nobody
    votes on their own proof. A tie approves, and so does a window that closes
    with too few votes: the group failing to agree must not cost the day to
    someone who did upload something on time.

    In a two-person challenge there is exactly one reviewer, so a partner can
    approve or reject on their own. That is deliberate.
    """
    if eligible_reviewers <= 0:
        # Nobody is allowed to vote, so only the closing window can settle it.
        return None
    if approvals * 2 > eligible_reviewers:
        return CheckInStatus.APPROVED
    if rejections * 2 > eligible_reviewers:
        return CheckInStatus.REJECTED
    if approvals + rejections >= eligible_reviewers:
        # Everyone voted and neither side reached a majority: an even split approves.
        return CheckInStatus.APPROVED
    return None
