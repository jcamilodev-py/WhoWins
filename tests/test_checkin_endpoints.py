import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.challenge.models import Challenge, ChallengeMember, ChallengeStatus, DurationType, MemberRole
from app.checkin.models import CheckIn, CheckInStatus
from app.shared.storage.object_storage import ObjectStorage
from app.user.models import AuthProvider, Role, User

PASSWORD = "UserPassword123"
PHOTO_BYTES = b"pretend-this-is-a-photo"

# POSIX sign convention is inverted: Etc/GMT+12 is UTC-12 and Etc/GMT-14 is UTC+14.
# Being 26 hours apart, their local dates always differ.
FAR_WEST_TZ = "Etc/GMT+12"
FAR_EAST_TZ = "Etc/GMT-14"


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _create_user(db: AsyncSession, timezone: str = "UTC", display_name: str | None = "Test User") -> User:
    user = User(
        email=f"checkin_test_{uuid.uuid4().hex[:8]}@test.com",
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


async def _create_challenge(db: AsyncSession, creator: User, members: list[User] | None = None, **overrides):
    """Arranges a running challenge with its members, bypassing the API."""
    fields = {
        "title": "Gym at 6 AM",
        "invite_code": f"T-{uuid.uuid4().hex[:10].upper()}",
        "duration_type": DurationType.INDEFINITE,
        "start_date": _utc_today() - timedelta(days=1),
        "active_days": list(range(7)),
        "status": ChallengeStatus.ACTIVE,
        "created_by": creator.id,
    } | overrides
    challenge = Challenge(**fields)
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    db.add(ChallengeMember(challenge_id=challenge.id, user_id=creator.id, role=MemberRole.CREATOR))
    for member in members or []:
        db.add(ChallengeMember(challenge_id=challenge.id, user_id=member.id))
    await db.commit()
    return challenge


async def _upload_photo(client: AsyncClient, challenge_id, headers: dict[str, str], keys: list[str]) -> dict:
    """Asks for an upload URL and puts the bytes where it points, as the app would."""
    ticket = await client.post(
        f"/api/v1/challenges/{challenge_id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=headers,
    )
    assert ticket.status_code == 200, ticket.text
    body = ticket.json()
    keys.append(body["key"])
    async with httpx.AsyncClient() as http:
        put = await http.put(body["uploadUrl"], content=PHOTO_BYTES, headers={"Content-Type": body["contentType"]})
    assert put.status_code == 200
    return body


async def _submit(client: AsyncClient, challenge_id, headers: dict[str, str], keys: list[str]):
    upload = await _upload_photo(client, challenge_id, headers, keys)
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/checkins/confirm", json={"key": upload["key"]}, headers=headers
    )


# --- upload url ---


async def test_check_in_upload_url_without_token_returns_401(client: AsyncClient):
    response = await client.post(
        f"/api/v1/challenges/{uuid.uuid4()}/checkins/upload-url", json={"contentType": "image/jpeg"}
    )
    assert response.status_code == 401


async def test_check_in_upload_url_for_non_member_returns_404(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator)
    outsider = await _create_user(db_session)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, outsider),
    )

    assert response.status_code == 404


async def test_check_in_upload_url_is_scoped_to_member_and_challenge(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, member),
    )

    body = response.json()
    assert body["key"].startswith(f"challenges/{challenge.id}/checkins/{member.id}/")
    assert body["localDate"] == _utc_today().isoformat()


async def test_check_in_upload_url_rejects_a_non_image(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "application/pdf"},
        headers=await _login(client, member),
    )

    assert response.status_code == 400


async def test_check_in_on_a_rest_day_returns_400(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    # Every weekday except today, so today is always a rest day.
    active_days = [day for day in range(7) if day != _utc_today().weekday()]
    challenge = await _create_challenge(db_session, member, active_days=active_days)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, member),
    )

    assert response.status_code == 400


async def test_check_in_before_the_challenge_starts_returns_400(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session, member, start_date=_utc_today() + timedelta(days=3), status=ChallengeStatus.PENDING
    )

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, member),
    )

    assert response.status_code == 400


async def test_check_in_after_the_challenge_ends_returns_400(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session,
        member,
        duration_type=DurationType.DAYS_10,
        total_days=10,
        start_date=_utc_today() - timedelta(days=15),
        end_date=_utc_today() - timedelta(days=6),
    )

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, member),
    )

    assert response.status_code == 400


async def test_check_in_uses_the_members_own_calendar(client: AsyncClient, db_session: AsyncSession):
    # The same instant is a different date for these two, and each one checks in
    # against their own day.
    west_member = await _create_user(db_session, timezone=FAR_WEST_TZ)
    east_member = await _create_user(db_session, timezone=FAR_EAST_TZ)
    challenge = await _create_challenge(
        db_session, west_member, members=[east_member], start_date=_utc_today() - timedelta(days=5)
    )

    west = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, west_member),
    )
    east = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, east_member),
    )

    assert west.json()["localDate"] == datetime.now(ZoneInfo(FAR_WEST_TZ)).date().isoformat()
    assert east.json()["localDate"] == datetime.now(ZoneInfo(FAR_EAST_TZ)).date().isoformat()
    assert west.json()["localDate"] != east.json()["localDate"]


# --- confirming ---


async def test_confirmed_check_in_is_approved_when_the_challenge_needs_no_review(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, requires_approval=False)
    headers = await _login(client, member)

    response = await _submit(client, challenge.id, headers, uploaded_keys)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "APPROVED"
    # Nothing to vote on, so no window to close.
    assert body["reviewClosesAt"] is None
    assert body["localDate"] == _utc_today().isoformat()
    async with httpx.AsyncClient() as http:
        stored = await http.get(body["photoUrl"])
    assert stored.content == PHOTO_BYTES


async def test_confirmed_check_in_waits_for_review_when_the_challenge_requires_it(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, requires_approval=True)
    headers = await _login(client, member)

    response = await _submit(client, challenge.id, headers, uploaded_keys)

    body = response.json()
    assert body["status"] == "PENDING_REVIEW"
    # Voting closes at the end of the following day, in the member's timezone.
    expected = datetime.combine(_utc_today() + timedelta(days=2), datetime.min.time(), tzinfo=ZoneInfo("UTC"))
    assert datetime.fromisoformat(body["reviewClosesAt"]) == expected


async def test_confirming_another_members_upload_returns_400(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    owner = await _create_user(db_session)
    thief = await _create_user(db_session)
    challenge = await _create_challenge(db_session, owner, members=[thief])
    upload = await _upload_photo(client, challenge.id, await _login(client, owner), uploaded_keys)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/confirm",
        json={"key": upload["key"]},
        headers=await _login(client, thief),
    )

    assert response.status_code == 400


async def test_confirming_a_key_that_was_never_uploaded_returns_400(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    response = await client.post(
        f"/api/v1/challenges/{challenge.id}/checkins/confirm",
        json={"key": f"challenges/{challenge.id}/checkins/{member.id}/missing.jpg"},
        headers=await _login(client, member),
    )

    assert response.status_code == 400


async def test_several_photos_on_the_same_day_are_all_kept(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)
    headers = await _login(client, member)

    first = await _submit(client, challenge.id, headers, uploaded_keys)
    second = await _submit(client, challenge.id, headers, uploaded_keys)

    assert first.status_code == 201
    assert second.status_code == 201
    stored = (
        (
            await db_session.execute(
                select(CheckIn).where(CheckIn.challenge_id == challenge.id, CheckIn.user_id == member.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 2


# --- today ---


async def test_today_status_without_token_returns_401(client: AsyncClient):
    response = await client.get(f"/api/v1/challenges/{uuid.uuid4()}/checkins/today")
    assert response.status_code == 401


async def test_today_status_for_non_member_returns_404(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator)
    outsider = await _create_user(db_session)

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, outsider)
    )

    assert response.status_code == 404


async def test_today_status_separates_who_submitted_from_who_did_not(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    done = await _create_user(db_session, display_name="Valentina")
    missing = await _create_user(db_session, display_name="Juan")
    challenge = await _create_challenge(db_session, done, members=[missing])
    await _submit(client, challenge.id, await _login(client, done), uploaded_keys)

    response = await client.get(f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, done))

    assert response.status_code == 200
    by_name = {member["displayName"]: member for member in response.json()["members"]}
    assert by_name["Valentina"]["status"] == "DONE"
    assert by_name["Valentina"]["photoUrl"] is not None
    assert by_name["Juan"]["status"] == "MISSING"
    assert by_name["Juan"]["photoUrl"] is None


async def test_today_status_reports_a_pending_photo_as_awaiting_review(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, requires_approval=True)
    headers = await _login(client, member)
    await _submit(client, challenge.id, headers, uploaded_keys)

    response = await client.get(f"/api/v1/challenges/{challenge.id}/checkins/today", headers=headers)

    assert response.json()["members"][0]["status"] == "AWAITING_REVIEW"


async def test_today_status_ignores_a_rejected_photo(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, requires_approval=True)
    headers = await _login(client, member)
    confirmed = await _submit(client, challenge.id, headers, uploaded_keys)
    check_in = await db_session.get(CheckIn, uuid.UUID(confirmed.json()["id"]))
    assert check_in is not None
    check_in.status = CheckInStatus.REJECTED
    await db_session.commit()

    response = await client.get(f"/api/v1/challenges/{challenge.id}/checkins/today", headers=headers)

    # The day is owed again: a rejected photo covers nothing.
    assert response.json()["members"][0]["status"] == "MISSING"


async def test_today_status_marks_a_rest_day_as_rest(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    active_days = [day for day in range(7) if day != _utc_today().weekday()]
    challenge = await _create_challenge(db_session, member, active_days=active_days)

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, member)
    )

    assert response.json()["members"][0]["status"] == "REST_DAY"
    assert response.json()["members"][0]["isActiveDay"] is False


async def test_today_status_gives_each_member_their_own_date(client: AsyncClient, db_session: AsyncSession):
    west_member = await _create_user(db_session, timezone=FAR_WEST_TZ, display_name="West")
    east_member = await _create_user(db_session, timezone=FAR_EAST_TZ, display_name="East")
    challenge = await _create_challenge(
        db_session, west_member, members=[east_member], start_date=_utc_today() - timedelta(days=5)
    )

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, west_member)
    )

    body = response.json()
    by_name = {member["displayName"]: member for member in body["members"]}
    assert by_name["West"]["localDate"] == datetime.now(ZoneInfo(FAR_WEST_TZ)).date().isoformat()
    assert by_name["East"]["localDate"] == datetime.now(ZoneInfo(FAR_EAST_TZ)).date().isoformat()
    assert body["viewerLocalDate"] == by_name["West"]["localDate"]


async def test_today_status_does_not_expose_emails(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    other = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, members=[other])

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/checkins/today", headers=await _login(client, member)
    )

    assert member.email not in response.text
    assert other.email not in response.text
