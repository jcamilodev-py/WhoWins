import re
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.challenge.models import (
    Challenge,
    ChallengeMember,
    ChallengeStatus,
    DurationType,
    LateJoinPolicy,
    MemberRole,
)
from app.challenge.service import INVITE_CODE_ALPHABET
from app.user.models import AuthProvider, Role, User

PASSWORD = "UserPassword123"
INVITE_CODE_PATTERN = re.compile(rf"^WINS-[{INVITE_CODE_ALPHABET}]{{4}}$")

# POSIX sign convention is inverted: Etc/GMT+12 is UTC-12 and Etc/GMT-14 is UTC+14.
# Being 26 hours apart, their local dates always differ.
FAR_WEST_TZ = "Etc/GMT+12"
FAR_EAST_TZ = "Etc/GMT-14"


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _create_user(db: AsyncSession, timezone: str = "UTC") -> User:
    user = User(
        email=f"challenge_test_{uuid.uuid4().hex[:8]}@test.com",
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
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def _insert_challenge(db: AsyncSession, creator: User, **overrides) -> Challenge:
    """Arranges a challenge directly, bypassing the API's start-date validation."""
    fields = {
        "title": "Arranged challenge",
        "invite_code": f"T-{uuid.uuid4().hex[:10].upper()}",
        "duration_type": DurationType.INDEFINITE,
        "start_date": _utc_today(),
        "created_by": creator.id,
    } | overrides
    challenge = Challenge(**fields)
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)
    return challenge


async def _find_member(db: AsyncSession, challenge_id: uuid.UUID, user_id: uuid.UUID) -> ChallengeMember | None:
    result = await db.execute(
        select(ChallengeMember).where(ChallengeMember.challenge_id == challenge_id, ChallengeMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _create_payload(**overrides) -> dict:
    return {
        "title": "Gym at 6 AM",
        "durationType": "DAYS_30",
        "startDate": _utc_today().isoformat(),
    } | overrides


# --- create ---


async def test_create_challenge_without_token_returns_401(client: AsyncClient):
    response = await client.post("/api/v1/challenges", json=_create_payload())
    assert response.status_code == 401


async def test_create_challenge_starting_today_returns_201_active(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)

    response = await client.post("/api/v1/challenges", json=_create_payload(), headers=headers)

    assert response.status_code == 201
    data = response.json()
    assert INVITE_CODE_PATTERN.match(data["inviteCode"])
    assert data["status"] == "ACTIVE"
    assert data["totalDays"] == 30
    assert data["endDate"] == (_utc_today() + timedelta(days=29)).isoformat()
    assert data["activeDays"] == [0, 1, 2, 3, 4, 5, 6]
    assert data["visibility"] == "PRIVATE"
    assert data["createdBy"] == str(user.id)


async def test_create_challenge_with_future_start_is_pending(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    start = _utc_today() + timedelta(days=5)

    response = await client.post(
        "/api/v1/challenges", json=_create_payload(startDate=start.isoformat()), headers=headers
    )

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"


async def test_create_indefinite_challenge_has_no_total_days_or_end_date(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)

    response = await client.post("/api/v1/challenges", json=_create_payload(durationType="INDEFINITE"), headers=headers)

    assert response.status_code == 201
    assert response.json()["totalDays"] is None
    assert response.json()["endDate"] is None


async def test_create_challenge_with_past_start_date_returns_400(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    yesterday = _utc_today() - timedelta(days=1)

    response = await client.post(
        "/api/v1/challenges", json=_create_payload(startDate=yesterday.isoformat()), headers=headers
    )

    assert response.status_code == 400


async def test_create_challenge_validates_start_date_in_user_timezone(client: AsyncClient, db_session: AsyncSession):
    west_today = datetime.now(ZoneInfo(FAR_WEST_TZ)).date()

    west_user = await _create_user(db_session, timezone=FAR_WEST_TZ)
    west_response = await client.post(
        "/api/v1/challenges",
        json=_create_payload(startDate=west_today.isoformat()),
        headers=await _login(client, west_user),
    )

    east_user = await _create_user(db_session, timezone=FAR_EAST_TZ)
    east_response = await client.post(
        "/api/v1/challenges",
        json=_create_payload(startDate=west_today.isoformat()),
        headers=await _login(client, east_user),
    )

    assert west_response.status_code == 201
    assert east_response.status_code == 400


async def test_create_challenge_ignores_client_supplied_derived_fields(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    payload = _create_payload(durationType="DAYS_10", inviteCode="WINS-HACK", status="COMPLETED", totalDays=999)

    response = await client.post("/api/v1/challenges", json=payload, headers=headers)

    data = response.json()
    assert data["inviteCode"] != "WINS-HACK"
    assert data["status"] == "ACTIVE"
    assert data["totalDays"] == 10


async def test_create_challenge_adds_creator_as_member(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)
    headers = await _login(client, user)

    response = await client.post("/api/v1/challenges", json=_create_payload(), headers=headers)

    member = await _find_member(db_session, uuid.UUID(response.json()["id"]), user.id)
    assert member is not None
    assert member.role == MemberRole.CREATOR


# --- join ---


async def test_join_challenge_with_lowercase_padded_code_returns_200(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    created = await client.post("/api/v1/challenges", json=_create_payload(), headers=await _login(client, creator))
    invite_code = created.json()["inviteCode"]

    joiner = await _create_user(db_session)
    response = await client.post(
        "/api/v1/challenges/join",
        json={"inviteCode": f"  {invite_code.lower()} "},
        headers=await _login(client, joiner),
    )

    assert response.status_code == 200
    member = await _find_member(db_session, uuid.UUID(created.json()["id"]), joiner.id)
    assert member is not None
    assert member.role == MemberRole.MEMBER
    assert member.missed_days_count == 0


async def test_join_challenge_without_token_returns_401(client: AsyncClient):
    response = await client.post("/api/v1/challenges/join", json={"inviteCode": "WINS-AAAA"})
    assert response.status_code == 401


async def test_join_challenge_with_unknown_code_returns_404(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": "WINS-NONE"}, headers=await _login(client, user)
    )

    assert response.status_code == 404


async def test_join_challenge_twice_returns_409(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(db_session, creator)
    joiner = await _create_user(db_session)
    headers = await _login(client, joiner)

    first = await client.post("/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=headers)
    second = await client.post("/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409


async def test_creator_joining_own_challenge_returns_409(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    headers = await _login(client, creator)
    created = await client.post("/api/v1/challenges", json=_create_payload(), headers=headers)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": created.json()["inviteCode"]}, headers=headers
    )

    assert response.status_code == 409


async def test_join_started_closed_challenge_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(
        db_session,
        creator,
        start_date=_utc_today() - timedelta(days=3),
        late_join_policy=LateJoinPolicy.CLOSED,
        status=ChallengeStatus.ACTIVE,
    )
    joiner = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    assert response.status_code == 400


async def test_join_pending_closed_challenge_is_allowed(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(
        db_session,
        creator,
        start_date=_utc_today() + timedelta(days=2),
        late_join_policy=LateJoinPolicy.CLOSED,
    )
    joiner = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    assert response.status_code == 200


async def test_join_started_inherit_missed_challenge_counts_elapsed_active_days(
    client: AsyncClient, db_session: AsyncSession
):
    creator = await _create_user(db_session)
    # Any 7 consecutive days contain exactly 5 weekdays, whatever today is.
    challenge = await _insert_challenge(
        db_session,
        creator,
        start_date=_utc_today() - timedelta(days=7),
        active_days=[0, 1, 2, 3, 4],
        late_join_policy=LateJoinPolicy.INHERIT_MISSED,
        status=ChallengeStatus.ACTIVE,
    )
    joiner = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    assert response.status_code == 200
    member = await _find_member(db_session, challenge.id, joiner.id)
    assert member is not None
    assert member.missed_days_count == 5


async def test_join_inherit_missed_challenge_on_start_day_inherits_nothing(
    client: AsyncClient, db_session: AsyncSession
):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(
        db_session, creator, start_date=_utc_today(), late_join_policy=LateJoinPolicy.INHERIT_MISSED
    )
    joiner = await _create_user(db_session)

    await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    member = await _find_member(db_session, challenge.id, joiner.id)
    assert member is not None
    assert member.missed_days_count == 0


async def test_join_started_clean_challenge_starts_with_zero_missed_days(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(
        db_session,
        creator,
        start_date=_utc_today() - timedelta(days=7),
        late_join_policy=LateJoinPolicy.CLEAN,
        status=ChallengeStatus.ACTIVE,
    )
    joiner = await _create_user(db_session)

    await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    member = await _find_member(db_session, challenge.id, joiner.id)
    assert member is not None
    assert member.missed_days_count == 0


async def test_join_cancelled_challenge_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(db_session, creator, status=ChallengeStatus.CANCELLED)
    joiner = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    assert response.status_code == 400


async def test_join_ended_challenge_returns_400(client: AsyncClient, db_session: AsyncSession):
    creator = await _create_user(db_session)
    challenge = await _insert_challenge(
        db_session,
        creator,
        duration_type=DurationType.DAYS_10,
        total_days=10,
        start_date=_utc_today() - timedelta(days=15),
        end_date=_utc_today() - timedelta(days=6),
        status=ChallengeStatus.ACTIVE,
    )
    joiner = await _create_user(db_session)

    response = await client.post(
        "/api/v1/challenges/join", json={"inviteCode": challenge.invite_code}, headers=await _login(client, joiner)
    )

    assert response.status_code == 400
