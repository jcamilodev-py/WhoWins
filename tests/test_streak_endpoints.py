"""The streak engine wired to real requests.

The arithmetic itself lives in tests/test_streak_engine.py, which can fix the
dates. These tests only check that the engine is actually reached, reads the
real check-ins, and stores what it computed.
"""

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
# Being 26 hours apart, their local dates are always exactly one day apart.
FAR_WEST_TZ = "Etc/GMT+12"
FAR_EAST_TZ = "Etc/GMT-14"


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _create_user(db: AsyncSession, display_name: str | None = "Test User", timezone: str = "UTC") -> User:
    user = User(
        email=f"streak_test_{uuid.uuid4().hex[:8]}@test.com",
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
    client.cookies.clear()
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def _create_challenge(
    db: AsyncSession,
    creator: User,
    members: list[User] | None = None,
    joined_days_ago: int = 0,
    **overrides,
):
    """A challenge with its members.

    `joined_days_ago` backdates the memberships: a challenge that started three
    days ago had members three days ago, and the engine only charges a member
    for days that ran after they joined.
    """
    fields = {
        "title": "Gym at 6 AM",
        "invite_code": f"T-{uuid.uuid4().hex[:10].upper()}",
        "duration_type": DurationType.INDEFINITE,
        "start_date": _utc_today(),
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
    for member in members or []:
        db.add(ChallengeMember(challenge_id=challenge.id, user_id=member.id, joined_at=joined_at))
    await db.commit()
    return challenge


async def _submit(client: AsyncClient, challenge_id, headers: dict[str, str], keys: list[str]):
    ticket = await client.post(
        f"/api/v1/challenges/{challenge_id}/checkins/upload-url",
        json={"contentType": "image/jpeg"},
        headers=headers,
    )
    body = ticket.json()
    keys.append(body["key"])
    async with httpx.AsyncClient() as http:
        await http.put(body["uploadUrl"], content=PHOTO_BYTES, headers={"Content-Type": body["contentType"]})
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/checkins/confirm", json={"key": body["key"]}, headers=headers
    )


async def _member_row(db: AsyncSession, challenge_id, user_id) -> ChallengeMember:
    member = (
        await db.execute(
            select(ChallengeMember).where(
                ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id
            )
        )
    ).scalar_one()
    await db.refresh(member)
    return member


async def test_confirming_the_only_members_proof_starts_both_streaks(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    await _submit(client, challenge.id, await _login(client, member), uploaded_keys)

    stored = await _member_row(db_session, challenge.id, member.id)
    await db_session.refresh(challenge)
    assert stored.current_individual_streak == 1
    assert stored.best_individual_streak == 1
    assert challenge.current_group_streak == 1


async def test_the_group_streak_waits_for_the_member_who_has_not_uploaded(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    ana = await _create_user(db_session, display_name="Ana")
    bob = await _create_user(db_session, display_name="Bob")
    challenge = await _create_challenge(db_session, ana, members=[bob])

    await _submit(client, challenge.id, await _login(client, ana), uploaded_keys)

    await db_session.refresh(challenge)
    ana_row = await _member_row(db_session, challenge.id, ana.id)
    assert ana_row.current_individual_streak == 1
    # Bob still has until his own midnight, so the day is not won yet.
    assert challenge.current_group_streak == 0


async def test_the_group_streak_counts_the_day_once_everyone_uploads(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    ana = await _create_user(db_session)
    bob = await _create_user(db_session)
    challenge = await _create_challenge(db_session, ana, members=[bob])

    await _submit(client, challenge.id, await _login(client, ana), uploaded_keys)
    await _submit(client, challenge.id, await _login(client, bob), uploaded_keys)

    await db_session.refresh(challenge)
    assert challenge.current_group_streak == 1


async def test_opening_the_challenge_charges_the_days_that_were_let_slip(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    # Started three days ago and nobody ever uploaded anything.
    challenge = await _create_challenge(
        db_session, member, start_date=_utc_today() - timedelta(days=3), joined_days_ago=3
    )
    headers = await _login(client, member)

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)

    # Three days are settled; today is still open, so it is not charged.
    assert response.json()["leaderboard"][0]["missedDaysCount"] == 3
    stored = await _member_row(db_session, challenge.id, member.id)
    assert stored.missed_days_count == 3


async def test_a_rejected_proof_leaves_the_day_uncovered(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member, requires_approval=True)
    headers = await _login(client, member)
    confirmed = await _submit(client, challenge.id, headers, uploaded_keys)

    before = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)
    check_in = await db_session.get(CheckIn, uuid.UUID(confirmed.json()["id"]))
    assert check_in is not None
    check_in.status = CheckInStatus.REJECTED
    await db_session.commit()
    after = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)

    # Waiting for the vote covers the day; being rejected takes it back.
    assert before.json()["leaderboard"][0]["currentIndividualStreak"] == 1
    assert after.json()["leaderboard"][0]["currentIndividualStreak"] == 0


async def test_reading_the_challenge_twice_changes_nothing_the_second_time(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session, member, start_date=_utc_today() - timedelta(days=2), joined_days_ago=2
    )
    headers = await _login(client, member)
    await _submit(client, challenge.id, headers, uploaded_keys)

    first = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)
    second = await client.get(f"/api/v1/challenges/{challenge.id}", headers=headers)

    # Recomputing is safe to repeat: the scores are a cache of the check-ins.
    assert first.json()["leaderboard"] == second.json()["leaderboard"]
    assert first.json()["challenge"]["currentGroupStreak"] == second.json()["challenge"]["currentGroupStreak"]


async def test_late_joiners_keep_the_days_they_inherited(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    creator = await _create_user(db_session)
    joiner = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session, creator, start_date=_utc_today() - timedelta(days=4), joined_days_ago=4
    )
    db_session.add(
        ChallengeMember(
            challenge_id=challenge.id,
            user_id=joiner.id,
            missed_days_count=4,
            inherited_missed_days=4,
        )
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, joiner))

    entries = {entry["userId"]: entry for entry in response.json()["leaderboard"]}
    # The joiner keeps the four inherited days but is not charged for the days
    # that ran before they were a member.
    assert entries[str(joiner.id)]["missedDaysCount"] == 4
    assert entries[str(creator.id)]["missedDaysCount"] == 4


async def test_each_member_is_charged_on_their_own_calendar(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    # The same instant, 26 hours apart: the eastern member is already living the
    # day after the western one, so the challenge's first day is settled for one
    # of them and still open for the other.
    west = await _create_user(db_session, display_name="West", timezone=FAR_WEST_TZ)
    east = await _create_user(db_session, display_name="East", timezone=FAR_EAST_TZ)
    west_today = datetime.now(ZoneInfo(FAR_WEST_TZ)).date()
    challenge = await _create_challenge(db_session, west, members=[east], start_date=west_today, joined_days_ago=2)

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, west))

    scores = {entry["displayName"]: entry["missedDaysCount"] for entry in response.json()["leaderboard"]}
    # Nobody uploaded anything: the eastern member already lost that day, while
    # the western one still has until their own midnight.
    assert scores == {"East": 1, "West": 0}


async def test_reading_a_challenge_that_started_flips_it_to_active(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    # Arranged as PENDING although its start date has already arrived: this is
    # what every challenge created before today looks like, since nothing moved
    # the status over time.
    challenge = await _create_challenge(
        db_session, member, start_date=_utc_today(), status=ChallengeStatus.PENDING, joined_days_ago=1
    )

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, member))

    assert response.json()["challenge"]["status"] == "ACTIVE"
    await db_session.refresh(challenge)
    assert challenge.status == ChallengeStatus.ACTIVE


async def test_reading_a_challenge_whose_last_day_passed_completes_it(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session,
        member,
        duration_type=DurationType.DAYS_10,
        total_days=10,
        start_date=_utc_today() - timedelta(days=15),
        end_date=_utc_today() - timedelta(days=6),
        joined_days_ago=15,
    )

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, member))

    assert response.json()["challenge"]["status"] == "COMPLETED"


async def test_a_challenge_still_running_is_not_completed(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session,
        member,
        duration_type=DurationType.DAYS_10,
        total_days=10,
        start_date=_utc_today() - timedelta(days=2),
        end_date=_utc_today() + timedelta(days=7),
        joined_days_ago=2,
    )

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, member))

    assert response.json()["challenge"]["status"] == "ACTIVE"


async def test_the_challenge_list_shows_refreshed_scores(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    member = await _create_user(db_session)
    # Two days went by with nothing uploaded, and the status was never moved.
    challenge = await _create_challenge(
        db_session,
        member,
        start_date=_utc_today() - timedelta(days=2),
        status=ChallengeStatus.PENDING,
        joined_days_ago=2,
    )

    response = await client.get("/api/v1/challenges", headers=await _login(client, member))

    item = next(item for item in response.json() if item["challenge"]["id"] == str(challenge.id))
    assert item["challenge"]["status"] == "ACTIVE"
    assert item["myMembership"]["missedDaysCount"] == 2


# --- who broke it ---


async def test_the_challenge_names_who_broke_the_group_streak(client: AsyncClient, db_session: AsyncSession):
    ana = await _create_user(db_session, display_name="Ana")
    bob = await _create_user(db_session, display_name="Bob")
    yesterday = _utc_today() - timedelta(days=1)
    challenge = await _create_challenge(db_session, ana, members=[bob], start_date=yesterday, joined_days_ago=1)
    # Ana covered yesterday; Bob did not.
    db_session.add(
        CheckIn(
            challenge_id=challenge.id,
            user_id=ana.id,
            local_date=yesterday,
            photo_key=f"challenges/{challenge.id}/checkins/{ana.id}/proof.jpg",
            status=CheckInStatus.APPROVED,
        )
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, ana))

    last_break = response.json()["lastGroupBreak"]
    assert last_break["day"] == yesterday.isoformat()
    assert [member["displayName"] for member in last_break["members"]] == ["Bob"]


async def test_a_group_that_never_lost_a_day_has_no_break(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    response = await client.get(f"/api/v1/challenges/{challenge.id}", headers=await _login(client, member))

    assert response.json()["lastGroupBreak"] is None


# --- day by day ---


async def test_the_history_draws_every_day_for_every_member(client: AsyncClient, db_session: AsyncSession):
    ana = await _create_user(db_session, display_name="Ana")
    today = _utc_today()
    yesterday = today - timedelta(days=1)
    before_yesterday = today - timedelta(days=2)
    # Every day is active except the day before yesterday, which is a rest day.
    challenge = await _create_challenge(
        db_session,
        ana,
        start_date=before_yesterday,
        active_days=[day for day in range(7) if day != before_yesterday.weekday()],
        joined_days_ago=2,
    )
    db_session.add(
        CheckIn(
            challenge_id=challenge.id,
            user_id=ana.id,
            local_date=yesterday,
            photo_key=f"challenges/{challenge.id}/checkins/{ana.id}/proof.jpg",
            status=CheckInStatus.APPROVED,
        )
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=await _login(client, ana))

    assert response.status_code == 200
    body = response.json()
    assert body["dates"] == [before_yesterday.isoformat(), yesterday.isoformat(), today.isoformat()]
    outcomes = [day["outcome"] for day in body["members"][0]["days"]]
    assert outcomes == ["REST_DAY", "COVERED", "OPEN"]


async def test_the_history_marks_days_before_joining(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session, display_name="Creator")
    latecomer = await _create_user(db_session, display_name="Latecomer")
    today = _utc_today()
    challenge = await _create_challenge(db_session, creator, start_date=today - timedelta(days=2), joined_days_ago=2)
    # Joined today: the two days before are not theirs to answer for.
    db_session.add(ChallengeMember(challenge_id=challenge.id, user_id=latecomer.id))
    await db_session.commit()

    response = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=await _login(client, latecomer))

    rows = {member["displayName"]: member for member in response.json()["members"]}
    assert [day["outcome"] for day in rows["Latecomer"]["days"]] == ["NOT_JOINED", "NOT_JOINED", "OPEN"]
    assert [day["outcome"] for day in rows["Creator"]["days"]] == ["MISSED", "MISSED", "OPEN"]


async def test_the_history_returns_only_the_most_recent_days_asked_for(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(
        db_session, member, start_date=_utc_today() - timedelta(days=10), joined_days_ago=10
    )

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/history?days=3", headers=await _login(client, member)
    )

    dates = response.json()["dates"]
    assert len(dates) == 3
    assert dates[-1] == _utc_today().isoformat()


async def test_the_history_is_members_only(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _create_challenge(db_session, creator)
    outsider = await _create_user(db_session)

    response = await client.get(f"/api/v1/challenges/{challenge.id}/history", headers=await _login(client, outsider))

    assert response.status_code == 404


async def test_the_history_rejects_an_unbounded_request(client: AsyncClient, db_session: AsyncSession):
    member = await _create_user(db_session)
    challenge = await _create_challenge(db_session, member)

    response = await client.get(
        f"/api/v1/challenges/{challenge.id}/history?days=5000", headers=await _login(client, member)
    )

    assert response.status_code == 422
