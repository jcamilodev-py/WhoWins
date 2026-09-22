"""Leaving, removing members and cancelling, through the API.

Proofs and votes are arranged straight in the database, so none of this needs
object storage running.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.challenge.models import Challenge, ChallengeMember, ChallengeStatus, DurationType, MemberRole
from app.checkin.models import CheckIn, CheckInReview, CheckInStatus
from app.shared.timezones import local_today
from app.user.models import AuthProvider, Role, User

PASSWORD = "UserPassword123"

# POSIX sign convention is inverted: Etc/GMT+12 is UTC-12 and Etc/GMT-14 is UTC+14.
# Being 26 hours apart, their local dates always differ.
FAR_WEST_TZ = "Etc/GMT+12"
FAR_EAST_TZ = "Etc/GMT-14"


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _create_user(db: AsyncSession, display_name: str = "Test User", timezone: str = "UTC") -> User:
    user = User(
        email=f"membership_test_{uuid.uuid4().hex[:8]}@test.com",
        display_name=display_name,
        password=hash_password(PASSWORD),
        role=Role.USER,
        auth_provider=AuthProvider.LOCAL,
        email_verified=True,
        active=True,
        timezone=timezone,
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


async def _create_challenge(
    db: AsyncSession, creator: User, members: list[User], joined_days_ago: int = 0, **overrides
) -> Challenge:
    """`joined_days_ago` backdates the memberships together with the start date."""
    fields = {
        "title": "Gym at 6 AM",
        "invite_code": f"T-{uuid.uuid4().hex[:10].upper()}",
        "duration_type": DurationType.INDEFINITE,
        "start_date": _utc_today() - timedelta(days=joined_days_ago),
        "active_days": list(range(7)),
        "status": ChallengeStatus.ACTIVE,
        "created_by": creator.id,
    } | overrides
    challenge = Challenge(**fields)
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    joined_at = datetime.now(UTC) - timedelta(days=joined_days_ago)
    db.add(ChallengeMember(challenge_id=challenge.id, user_id=creator.id, role=MemberRole.CREATOR, joined_at=joined_at))
    for member in members:
        db.add(ChallengeMember(challenge_id=challenge.id, user_id=member.id, joined_at=joined_at))
    await db.commit()
    return challenge


async def _add_proof(
    db: AsyncSession,
    challenge: Challenge,
    author: User,
    status: CheckInStatus = CheckInStatus.APPROVED,
    review_closes_at: datetime | None = None,
) -> CheckIn:
    check_in = CheckIn(
        challenge_id=challenge.id,
        user_id=author.id,
        local_date=_utc_today(),
        photo_key=f"challenges/{challenge.id}/checkins/{author.id}/{uuid.uuid4().hex}.jpg",
        status=status,
        review_closes_at=review_closes_at,
    )
    db.add(check_in)
    await db.commit()
    await db.refresh(check_in)
    return check_in


async def _add_vote(db: AsyncSession, check_in: CheckIn, reviewer: User, is_approved: bool) -> None:
    db.add(CheckInReview(check_in_id=check_in.id, reviewer_id=reviewer.id, is_approved=is_approved))
    await db.commit()


async def _member_row(db: AsyncSession, challenge_id, user_id) -> ChallengeMember:
    result = await db.execute(
        select(ChallengeMember).where(ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id)
    )
    member = result.scalar_one()
    await db.refresh(member)
    return member


async def _leave(client: AsyncClient, challenge_id, headers: dict[str, str]):
    return await client.post(f"/api/v1/challenges/{challenge_id}/leave", headers=headers)


async def _remove(client: AsyncClient, challenge_id, user_id, headers: dict[str, str]):
    return await client.delete(f"/api/v1/challenges/{challenge_id}/members/{user_id}", headers=headers)


async def _cancel(client: AsyncClient, challenge_id, headers: dict[str, str]):
    return await client.post(f"/api/v1/challenges/{challenge_id}/cancel", headers=headers)


# --- leaving ---


async def test_leave_without_token_returns_401(client: AsyncClient):
    response = await client.post(f"/api/v1/challenges/{uuid.uuid4()}/leave")
    assert response.status_code == 401


async def test_a_member_who_leaves_loses_access_to_the_challenge(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob])
    headers = await _login(client, bob)

    response = await _leave(client, challenge.id, headers)

    assert response.status_code == 204
    listing = await client.get("/api/v1/challenges", headers=headers)
    assert listing.json() == []
    detail = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)
    assert detail.status_code == 404
    upload = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url", json={"contentType": "image/jpeg"}, headers=headers
    )
    assert upload.status_code == 404


async def test_the_creator_cannot_leave_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [await _create_user(db_session)])

    response = await _leave(client, challenge.id, await _login(client, creator))

    assert response.status_code == 400


async def test_leaving_a_challenge_you_are_not_in_returns_404(client: AsyncClient, db_session: AsyncSession):
    challenge = await _create_challenge(db_session, await _create_user(db_session), [])

    response = await _leave(client, challenge.id, await _login(client, await _create_user(db_session)))

    assert response.status_code == 404


async def test_leaving_twice_returns_404(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, await _create_user(db_session), [bob])
    headers = await _login(client, bob)
    await _leave(client, challenge.id, headers)

    response = await _leave(client, challenge.id, headers)

    assert response.status_code == 404


async def test_leaving_a_finished_challenge_returns_400(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    # Its last day was yesterday, so the ranking is final.
    challenge = await _create_challenge(
        db_session,
        await _create_user(db_session),
        [bob],
        joined_days_ago=10,
        duration_type=DurationType.DAYS_10,
        total_days=10,
        end_date=_utc_today() - timedelta(days=1),
    )

    response = await _leave(client, challenge.id, await _login(client, bob))

    assert response.status_code == 400
    assert (await _member_row(db_session, challenge.id, bob.id)).left_at is None


async def test_a_member_who_left_cannot_join_again_returns_400(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, await _create_user(db_session), [bob])
    headers = await _login(client, bob)
    await _leave(client, challenge.id, headers)

    response = await client.post("/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=headers)

    assert response.status_code == 400


async def test_preview_for_a_member_who_left_returns_left(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, await _create_user(db_session), [bob])
    headers = await _login(client, bob)
    await _leave(client, challenge.id, headers)

    response = await client.post(
        "/api/v1/challenges/preview", json={"inviteCode": challenge.invite_code}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["joinStatus"] == "LEFT"
    assert response.json()["missedDaysOnJoin"] is None
    assert response.json()["memberCount"] == 1


async def test_a_member_who_left_drops_out_of_the_ranking(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob])
    await _leave(client, challenge.id, await _login(client, bob))

    headers = await _login(client, creator)
    detail = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)
    listing = await client.get("/api/v1/challenges", headers=headers)

    assert [entry["userId"] for entry in detail.json()["leaderboard"]] == [str(creator.id)]
    assert listing.json()[0]["memberCount"] == 1


async def test_leaving_keeps_the_days_already_missed_and_the_blame(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session, display_name="Bob")
    challenge = await _create_challenge(db_session, creator, [bob], joined_days_ago=3)
    db_session.add_all(
        CheckIn(
            challenge_id=challenge.id,
            user_id=creator.id,
            local_date=_utc_today() - timedelta(days=offset),
            photo_key=f"challenges/{challenge.id}/checkins/{creator.id}/{offset}.jpg",
            status=CheckInStatus.APPROVED,
        )
        for offset in range(4)
    )
    await db_session.commit()

    await _leave(client, challenge.id, await _login(client, bob))

    assert (await _member_row(db_session, challenge.id, bob.id)).missed_days_count == 3
    detail = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, creator))
    group_break = detail.json()["lastGroupBreak"]
    assert group_break["day"] == (_utc_today() - timedelta(days=1)).isoformat()
    assert [member["displayName"] for member in group_break["members"]] == ["Bob"]


async def test_the_group_streak_stops_waiting_for_a_member_who_left(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob])
    await _add_proof(db_session, challenge, creator)

    await _leave(client, challenge.id, await _login(client, bob))

    await db_session.refresh(challenge)
    assert challenge.current_group_streak == 1


async def test_history_marks_the_days_after_someone_left(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob], joined_days_ago=1)
    await _leave(client, challenge.id, await _login(client, bob))

    response = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=await _login(client, creator))

    bob_row = next(member for member in response.json()["members"] if member["userId"] == str(bob.id))
    assert bob_row["leftAt"] is not None
    assert bob_row["removed"] is False
    assert [day["outcome"] for day in bob_row["days"]] == ["MISSED", "LEFT"]


async def test_history_leaves_out_someone_with_no_day_left_to_show(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob])
    await _leave(client, challenge.id, await _login(client, bob))

    response = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=await _login(client, creator))

    assert [member["userId"] for member in response.json()["members"]] == [str(creator.id)]


async def test_a_member_who_left_is_not_in_todays_status(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob])
    await _leave(client, challenge.id, await _login(client, bob))

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, creator)
    )

    assert [member["userId"] for member in response.json()["members"]] == [str(creator.id)]


async def test_a_challenge_that_had_only_started_for_whoever_left_is_pending_again(
    client: AsyncClient, db_session: AsyncSession
):
    creator = await _create_user(db_session, timezone=FAR_WEST_TZ)
    bob = await _create_user(db_session, timezone=FAR_EAST_TZ)
    # Today for Bob, still tomorrow or later for the creator.
    challenge = await _create_challenge(
        db_session, creator, [bob], start_date=local_today(FAR_EAST_TZ), status=ChallengeStatus.PENDING
    )

    await _leave(client, challenge.id, await _login(client, bob))

    await db_session.refresh(challenge)
    assert challenge.status == ChallengeStatus.PENDING


# --- removing a member ---


async def test_the_creator_can_remove_a_member(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob], joined_days_ago=1)
    headers = await _login(client, creator)

    response = await _remove(client, challenge.id, bob.id, headers)

    assert response.status_code == 204
    stored = await _member_row(db_session, challenge.id, bob.id)
    assert stored.left_at is not None
    assert stored.removed_by == creator.id
    history = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=headers)
    bob_row = next(member for member in history.json()["members"] if member["userId"] == str(bob.id))
    assert bob_row["removed"] is True
    detail = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, bob))
    assert detail.status_code == 404


async def test_a_member_who_is_not_the_creator_cannot_remove_returns_403(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [ana, bob])

    response = await _remove(client, challenge.id, bob.id, await _login(client, ana))

    assert response.status_code == 403
    assert (await _member_row(db_session, challenge.id, bob.id)).left_at is None


async def test_the_creator_cannot_remove_themselves_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [await _create_user(db_session)])

    response = await _remove(client, challenge.id, creator.id, await _login(client, creator))

    assert response.status_code == 400


async def test_removing_someone_who_is_not_a_member_returns_404(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [])
    outsider = await _create_user(db_session)

    response = await _remove(client, challenge.id, outsider.id, await _login(client, creator))

    assert response.status_code == 404


async def test_removing_from_a_challenge_you_are_not_in_returns_404(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, await _create_user(db_session), [bob])

    response = await _remove(client, challenge.id, bob.id, await _login(client, await _create_user(db_session)))

    assert response.status_code == 404


# --- peer review after someone leaves ---


async def test_a_departure_can_decide_a_pending_proof(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [ana, bob], requires_approval=True)
    proof = await _add_proof(
        db_session,
        challenge,
        creator,
        status=CheckInStatus.PENDING_REVIEW,
        review_closes_at=datetime.now(UTC) + timedelta(days=1),
    )
    # One rejection out of two reviewers is not a majority yet.
    await _add_vote(db_session, proof, ana, is_approved=False)

    await _leave(client, challenge.id, await _login(client, bob))

    await db_session.refresh(proof)
    assert proof.status == CheckInStatus.REJECTED


async def test_the_votes_of_a_member_who_left_stop_counting(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [ana, bob], requires_approval=True)
    proof = await _add_proof(
        db_session,
        challenge,
        creator,
        status=CheckInStatus.PENDING_REVIEW,
        review_closes_at=datetime.now(UTC) + timedelta(days=1),
    )
    await _add_vote(db_session, proof, bob, is_approved=True)

    await _leave(client, challenge.id, await _login(client, bob))

    await db_session.refresh(proof)
    assert proof.status == CheckInStatus.PENDING_REVIEW
    queue = await client.get(f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, ana))
    assert queue.json()[0]["approvals"] == 0
    assert queue.json()[0]["eligibleReviewers"] == 1


async def test_a_closed_window_is_not_turned_into_a_rejection_by_a_departure(
    client: AsyncClient, db_session: AsyncSession
):
    creator = await _create_user(db_session)
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [ana, bob], requires_approval=True)
    proof = await _add_proof(
        db_session,
        challenge,
        creator,
        status=CheckInStatus.PENDING_REVIEW,
        review_closes_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await _add_vote(db_session, proof, ana, is_approved=False)

    await _leave(client, challenge.id, await _login(client, bob))

    await db_session.refresh(proof)
    assert proof.status == CheckInStatus.APPROVED


async def test_a_member_who_left_cannot_vote(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [bob], requires_approval=True)
    proof = await _add_proof(
        db_session,
        challenge,
        creator,
        status=CheckInStatus.PENDING_REVIEW,
        review_closes_at=datetime.now(UTC) + timedelta(days=1),
    )
    headers = await _login(client, bob)
    await _leave(client, challenge.id, headers)

    response = await client.put(
        f"/api/v1/challenges/{challenge.id}/checkins/{proof.id}/review", json={"isApproved": False}, headers=headers
    )

    assert response.status_code == 404


async def test_everyone_still_in_reviews_the_proof_of_someone_who_left(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [ana, bob], requires_approval=True)
    await _add_proof(
        db_session,
        challenge,
        bob,
        status=CheckInStatus.PENDING_REVIEW,
        review_closes_at=datetime.now(UTC) + timedelta(days=1),
    )

    await _leave(client, challenge.id, await _login(client, bob))

    queue = await client.get(f"/api/v1/challenges/{challenge.id}/checkins/pending", headers=await _login(client, ana))
    assert queue.json()[0]["eligibleReviewers"] == 2


# --- cancelling ---


async def test_the_creator_can_cancel_a_challenge(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [await _create_user(db_session)])

    response = await _cancel(client, challenge.id, await _login(client, creator))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancelledAt"] is not None


async def test_a_member_who_is_not_the_creator_cannot_cancel_returns_403(client: AsyncClient, db_session: AsyncSession):
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, await _create_user(db_session), [bob])

    response = await _cancel(client, challenge.id, await _login(client, bob))

    assert response.status_code == 403
    await db_session.refresh(challenge)
    assert challenge.status == ChallengeStatus.ACTIVE


async def test_cancelling_twice_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator, [])
    headers = await _login(client, creator)
    await _cancel(client, challenge.id, headers)

    response = await _cancel(client, challenge.id, headers)

    assert response.status_code == 400


async def test_cancelling_a_challenge_you_are_not_in_returns_404(client: AsyncClient, db_session: AsyncSession):
    challenge = await _create_challenge(db_session, await _create_user(db_session), [])

    response = await _cancel(client, challenge.id, await _login(client, await _create_user(db_session)))

    assert response.status_code == 404


async def test_a_cancelled_challenge_stops_collecting_misses(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    # Started three days ago and cancelled on its second day, with nobody ever
    # uploading: only the first day closed before the cancellation.
    challenge = await _create_challenge(
        db_session,
        creator,
        [],
        joined_days_ago=3,
        status=ChallengeStatus.CANCELLED,
        cancelled_at=datetime.now(UTC) - timedelta(days=2),
    )

    await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, creator))

    assert (await _member_row(db_session, challenge.id, creator.id)).missed_days_count == 1
