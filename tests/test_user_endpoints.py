import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.user.models import AuthProvider, Role, User


def _generate_random_email() -> str:
    return f"admin_test_{uuid.uuid4().hex[:8]}@test.com"


async def _create_user_with_role(db: AsyncSession, email: str, role: Role, password: str = "securePassword123") -> User:

    user = User(
        email=email,
        password=hash_password(password),
        role=role,
        auth_provider=AuthProvider.LOCAL,
        email_verified=True,
        active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_admin_route_without_token_returns_401(client: AsyncClient):

    fake_id = uuid.uuid4()
    response = await client.get(f"/api/v1/users/{fake_id}")
    assert response.status_code == 401


async def test_admin_route_with_normal_user_returns_403(client: AsyncClient, db_session: AsyncSession):

    email = _generate_random_email()
    password = "UserPassword123"

    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"/api/v1/users/exists/{email}", headers=headers)

    assert response.status_code == 403
    assert "You do not have permission." in response.json()["detail"]


async def test_admin_route_with_admin_user_returns_200(client: AsyncClient, db_session: AsyncSession):

    email = _generate_random_email()
    password = "AdminPassword123"

    admin_user = await _create_user_with_role(db_session, email, Role.ADMIN, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"/api/v1/users/{admin_user.id}", headers=headers)

    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == email
    assert user_data["role"] == "ADMIN"
    assert user_data["timezone"] == "UTC"


async def test_get_me_unauthenticated_returns_401(client: AsyncClient):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


async def test_get_me_authenticated_returns_current_user(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"

    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == email
    assert data["role"] == "USER"
    assert data["timezone"] == "UTC"


async def test_patch_me_updates_timezone(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"

    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.patch(
        "/api/v1/users/me",
        json={"timezone": "America/Bogota"},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == "America/Bogota"

    # Verify subsequent GET /me reflects the change
    get_res = await client.get("/api/v1/users/me", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["timezone"] == "America/Bogota"


async def test_patch_me_invalid_timezone_returns_422(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"

    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.patch(
        "/api/v1/users/me",
        json={"timezone": "Mars/Olympus_Mons"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_get_me_without_display_name_returns_null(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"
    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    headers = {"Authorization": f"Bearer {login_res.json()['accessToken']}"}
    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["displayName"] is None


async def test_patch_me_sets_trimmed_display_name(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"
    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    headers = {"Authorization": f"Bearer {login_res.json()['accessToken']}"}
    response = await client.patch("/api/v1/users/me", json={"displayName": "  Camila  "}, headers=headers)

    assert response.status_code == 200
    assert response.json()["displayName"] == "Camila"
    get_res = await client.get("/api/v1/users/me", headers=headers)
    assert get_res.json()["displayName"] == "Camila"


async def test_patch_me_without_display_name_keeps_the_current_one(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"
    user = await _create_user_with_role(db_session, email, Role.USER, password)
    user.display_name = "Camila"
    await db_session.commit()

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    headers = {"Authorization": f"Bearer {login_res.json()['accessToken']}"}
    response = await client.patch("/api/v1/users/me", json={"timezone": "America/Bogota"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["displayName"] == "Camila"


async def test_patch_me_with_invalid_display_name_returns_422(client: AsyncClient, db_session: AsyncSession):
    email = _generate_random_email()
    password = "UserPassword123"
    await _create_user_with_role(db_session, email, Role.USER, password)

    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    headers = {"Authorization": f"Bearer {login_res.json()['accessToken']}"}
    blank = await client.patch("/api/v1/users/me", json={"displayName": "   "}, headers=headers)
    too_long = await client.patch("/api/v1/users/me", json={"displayName": "x" * 41}, headers=headers)

    assert blank.status_code == 422
    assert too_long.status_code == 422
