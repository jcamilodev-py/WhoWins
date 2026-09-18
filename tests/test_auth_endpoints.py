import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.user.models import User


def _generate_random_email() -> str:
    return f"user_{uuid.uuid4().hex[:8]}@test.com"


async def _find_user(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


def _register_payload(email: str, password: str = "securepassword123", display_name: str = "Test User") -> dict:
    return {"email": email, "password": password, "displayName": display_name}


async def test_register_user_success(client: AsyncClient):
    email = _generate_random_email()

    response = await client.post("/api/v1/auth/register", json=_register_payload(email, display_name="Valentina"))

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["displayName"] == "Valentina"
    assert data["role"] == "USER"
    assert "password" not in data


async def test_register_trims_display_name(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(_generate_random_email(), display_name="  Valentina  ")
    )

    assert response.status_code == 201
    assert response.json()["displayName"] == "Valentina"


async def test_register_without_display_name_returns_422(client: AsyncClient):
    payload = {"email": _generate_random_email(), "password": "securepassword123"}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422
    assert ["body", "displayName"] in [error["loc"] for error in response.json()["detail"]]


async def test_register_with_blank_display_name_returns_422(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(_generate_random_email(), display_name="   ")
    )

    assert response.status_code == 422


async def test_register_with_display_name_over_40_characters_returns_422(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload(_generate_random_email(), display_name="x" * 41)
    )

    assert response.status_code == 422


async def test_register_allows_duplicate_display_names(client: AsyncClient):
    first = await client.post(
        "/api/v1/auth/register", json=_register_payload(_generate_random_email(), display_name="Juan")
    )
    second = await client.post(
        "/api/v1/auth/register", json=_register_payload(_generate_random_email(), display_name="Juan")
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_register_duplicate_email_returns_bad_request(client: AsyncClient):
    payload = _register_payload(_generate_random_email())

    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400

    error_data = res2.json()
    assert "already registered" in error_data["message"]


async def test_login_success(client: AsyncClient):
    email = _generate_random_email()
    password = "MyStrongPassword_99"

    await client.post("/api/v1/auth/register", json=_register_payload(email, password, display_name="Andrés"))

    login_payload = {"username": email, "password": password}
    response = await client.post("/api/v1/auth/login", data=login_payload)

    assert response.status_code == 200
    data = response.json()

    assert "accessToken" in data
    assert data["tokenType"] == "bearer"
    assert data["user"]["email"] == email
    assert data["user"]["displayName"] == "Andrés"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


async def test_login_with_wrong_password_fails(client: AsyncClient):
    email = _generate_random_email()
    real_password = "realPassword"

    register_response = await client.post("/api/v1/auth/register", json=_register_payload(email, real_password))
    # Guards the premise: without an existing account the 401 below would prove nothing.
    assert register_response.status_code == 201

    wrong_payload = {"username": email, "password": "wrongPassword123"}
    response = await client.post("/api/v1/auth/login", data=wrong_payload)

    assert response.status_code == 401


async def test_get_me_unauthorized_without_token(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_get_me_authorized_with_token(client: AsyncClient):
    email = _generate_random_email()
    password = "SuperSecretPassword123"

    await client.post("/api/v1/auth/register", json=_register_payload(email, password, display_name="Sofía"))
    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    me_res = await client.get("/api/v1/auth/me", headers=headers)

    assert me_res.status_code == 200
    profile = me_res.json()
    assert profile["email"] == email
    assert profile["displayName"] == "Sofía"
    assert profile["active"] is True


# --- timezone at registration ---


async def test_register_stores_the_timezone_the_client_sends(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    payload = _register_payload(email) | {"timezone": "America/Bogota"}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201
    user = await _find_user(db_session, email)
    assert user is not None
    assert user.timezone == "America/Bogota"


async def test_register_without_a_timezone_falls_back_to_utc(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()

    await client.post("/api/v1/auth/register", json=_register_payload(email))

    user = await _find_user(db_session, email)
    assert user is not None
    # The account still works; its midnight is simply UTC until the profile says otherwise.
    assert user.timezone == "UTC"


async def test_register_with_an_invalid_timezone_returns_422(client: AsyncClient):
    payload = _register_payload(_generate_random_email()) | {"timezone": "Mars/Olympus_Mons"}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "timezone"]
