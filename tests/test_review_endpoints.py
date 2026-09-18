"""Peer review through the API.

Proofs are arranged straight in the database: these tests are about voting, not
about uploading, so they do not need object storage running. Signing a photo URL
is pure computation, so the responses still carry one.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.challenge.models import Challenge, ChallengeMember, ChallengeStatus, DurationType, MemberRole
from app.checkin.models import CheckIn, CheckInReview, CheckInStatus
from app.user.models import AuthProvider, Role, User

PASSWORD = "UserPassword123"


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _create_user(db: AsyncSession, display_name: str = "Test User") -> User:
    user = User(
        email=f"review_test_{uuid.uuid4().hex[:8]}@test.com",
        display_name=display_name,
        password=hash_password(PASSWORD),
        role=Role.USER,
        auth_provider=AuthProvider.LOCAL,
        email_verified=True,
        active=True,
        timezone="UTC",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", data={"username": user.email, "password": PASSWORD})
    # The auth dependency reads the cookie before the header, so a leftover
    # cookie would silently authenticate the next request as the previous user.
    client.cookies.clear()
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def _create_challenge(db: AsyncSession, creator: User, members: list[User] | None = None) -> Challenge:
    challenge = Challenge(
        title="Gym at 6 AM",
        invite_code=f"T-{uuid.uuid4().hex[:10].upper()}",
        duration_type=DurationType.INDEFINITE,
        start_date=_utc_today(),
        active_days=list(range(7)),
        status=ChallengeStatus.ACTIVE,
        requires_approval=True,
        created_by=creator.id,
    )
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    db.add(ChallengeMember(challenge_id=challenge.id, user_id=creator.id, role=MemberRole.CREATOR))
    for member in members or []:
        db.add(ChallengeMember(challenge_id=challenge.id, user_id=member.id))
    await db.commit()
    return challenge


async def _add_proof(
    db: AsyncSession,
    challenge: Challenge,
    author: User,
    status: CheckInStatus = CheckInStatus.PENDING_REVIEW,
    review_closes_at: datetime | None = None,
) -> CheckIn:
    check_in = CheckIn(
        challenge_id=challenge.id,
        user_id=author.id,
        local_date=_utc_today(),
        photo_key=f"challenges/{challenge.id}/checkins/{author.id}/{uuid.uuid4().hex}.jpg",
        status=status,
        review_closes_at=review_closes_at or (datetime.now(UTC) + timedelta(days=1)),
    )
    db.add(check_in)
    await db.commit()
    await db.refresh(check_in)
    return check_in


async def _member_row(db: AsyncSession, challenge_id, user_id) -> ChallengeMember:
    result = await db.execute(
        select(ChallengeMember).where(ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id)
    )
    member = result.scalar_one()
    await db.refresh(member)
    return member


def _vote_url(challenge_id, check_in_id) -> str:
    return f"/api/v1/challenges/{challenge_id}/checkins/{check_in_id}/review"


# --- who may vote ---


async def test_voting_without_token_returns_401(client: AsyncClient):
    response = await client.put(_vote_url(uuid.uuid4(), uuid.uuid4()), json={"isApproved": True})
    assert response.status_code == 401


async def test_a_non_member_cannot_vote(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator)
    check_in = await _add_proof(db_session, challenge, creator)
    outsider = await _create_user(db_session)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=await _login(client, outsider)
    )

    assert response.status_code == 404


async def test_a_member_cannot_vote_on_their_own_proof(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    other = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[other])
    check_in = await _add_proof(db_session, challenge, author)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=await _login(client, author)
    )

    assert response.status_code == 400


async def test_voting_on_a_proof_from_another_challenge_returns_404(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    reviewer = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[reviewer])
    other_challenge = await _create_challenge(db_session, author, members=[reviewer])
    check_in = await _add_proof(db_session, other_challenge, author)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=await _login(client, reviewer)
    )

    assert response.status_code == 404


# --- deciding ---


async def test_the_only_reviewer_approves_the_proof_alone(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session, display_name="Ana")
    partner = await _create_user(db_session, display_name="Bob")
    challenge = await _create_challenge(db_session, author, members=[partner])
    check_in = await _add_proof(db_session, challenge, author)

    response = await client.put(
        _vote_url(challenge.id, check_in.id),
        json={"isApproved": True, "comment": "Se ve la pesa"},
        headers=await _login(client, partner),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["approvals"] == 1
    assert body["eligibleReviewers"] == 1
    assert body["displayName"] == "Ana"
    assert body["myVote"] is True
    await db_session.refresh(check_in)
    assert check_in.status == CheckInStatus.APPROVED
    assert check_in.decided_at is not None


async def test_the_only_reviewer_rejects_the_proof_alone(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    partner = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[partner])
    check_in = await _add_proof(db_session, challenge, author)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=await _login(client, partner)
    )

    assert response.json()["status"] == "REJECTED"
    await db_session.refresh(check_in)
    assert check_in.status == CheckInStatus.REJECTED


async def test_one_vote_out_of_two_reviewers_leaves_the_proof_pending(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    first = await _create_user(db_session)
    second = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[first, second])
    check_in = await _add_proof(db_session, challenge, author)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=await _login(client, first)
    )

    body = response.json()
    assert body["status"] == "PENDING_REVIEW"
    assert body["eligibleReviewers"] == 2
    assert body["approvals"] == 1


async def test_a_split_vote_approves_the_proof(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    first = await _create_user(db_session)
    second = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[first, second])
    check_in = await _add_proof(db_session, challenge, author)

    await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=await _login(client, first)
    )
    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=await _login(client, second)
    )

    # Nobody reached a majority, so the member who uploaded keeps the day.
    assert response.json()["status"] == "APPROVED"


async def test_a_reviewer_can_change_their_vote_while_the_proof_is_open(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    first = await _create_user(db_session)
    second = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[first, second])
    check_in = await _add_proof(db_session, challenge, author)
    headers = await _login(client, first)

    await client.put(_vote_url(challenge.id, check_in.id), json={"isApproved": True}, headers=headers)
    response = await client.put(_vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=headers)

    body = response.json()
    # One vote, changed: not two.
    assert (body["approvals"], body["rejections"]) == (0, 1)
    assert body["status"] == "PENDING_REVIEW"


async def test_voting_on_a_decided_proof_returns_400(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    partner = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[partner])
    check_in = await _add_proof(db_session, challenge, author, status=CheckInStatus.APPROVED)

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=await _login(client, partner)
    )

    assert response.status_code == 400


async def test_a_closed_window_approves_the_proof_and_refuses_the_late_vote(
    client: AsyncClient, db_session: AsyncSession
):
    author = await _create_user(db_session)
    partner = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[partner])
    check_in = await _add_proof(
        db_session, challenge, author, review_closes_at=datetime.now(UTC) - timedelta(minutes=1)
    )

    response = await client.put(
        _vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=await _login(client, partner)
    )

    assert response.status_code == 400
    await db_session.refresh(check_in)
    # Silence approves: the member uploaded on time, the group did not vote in time.
    assert check_in.status == CheckInStatus.APPROVED


# --- the queue ---


async def test_the_pending_queue_lists_what_is_waiting(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session, display_name="Ana")
    reviewer = await _create_user(db_session, display_name="Bob")
    challenge = await _create_challenge(db_session, author, members=[reviewer])
    pending = await _add_proof(db_session, challenge, author)
    await _add_proof(db_session, challenge, author, status=CheckInStatus.APPROVED)

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, reviewer)
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(pending.id)]
    assert body[0]["displayName"] == "Ana"
    assert body[0]["myVote"] is None
    assert body[0]["photoUrl"].startswith("http")


async def test_the_pending_queue_shows_the_vote_already_cast(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    reviewer = await _create_user(db_session)
    third = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[reviewer, third])
    check_in = await _add_proof(db_session, challenge, author)
    db_session.add(CheckInReview(check_in_id=check_in.id, reviewer_id=reviewer.id, is_approved=True))
    await db_session.commit()

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, reviewer)
    )

    assert response.json()[0]["myVote"] is True
    assert response.json()[0]["approvals"] == 1


async def test_the_pending_queue_settles_windows_that_ran_out(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    reviewer = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[reviewer])
    expired = await _add_proof(db_session, challenge, author, review_closes_at=datetime.now(UTC) - timedelta(minutes=1))

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, reviewer)
    )

    assert response.json() == []
    await db_session.refresh(expired)
    assert expired.status == CheckInStatus.APPROVED


async def test_the_pending_queue_is_members_only(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator)
    outsider = await _create_user(db_session)

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, outsider)
    )

    assert response.status_code == 404


# --- what a rejection costs ---


async def test_rejecting_a_proof_takes_the_day_back(client: AsyncClient, db_session: AsyncSession):
    author = await _create_user(db_session)
    partner = await _create_user(db_session)
    challenge = await _create_challenge(db_session, author, members=[partner])
    await _add_proof(db_session, challenge, author)
    check_in = await _add_proof(db_session, challenge, partner)
    author_headers = await _login(client, author)
    # Reading the challenge once settles the scores as they stand: both members
    # are covered, because a proof waiting for the vote still counts.
    await client.get(f"/api/v1/challenges/{challenge.id}", headers=author_headers)
    partner_row = await _member_row(db_session, challenge.id, partner.id)
    assert partner_row.current_individual_streak == 1

    await client.put(_vote_url(challenge.id, check_in.id), json={"isApproved": False}, headers=author_headers)

    # Checked in the database rather than through the challenge endpoint: that
    # endpoint recalculates on its own, so reading it would hide whether the
    # vote itself updated the scores.
    await db_session.refresh(partner_row)
    assert partner_row.current_individual_streak == 0
    await db_session.refresh(challenge)
    assert challenge.current_group_streak == 0
