import uuid
from httpx import AsyncClient
import pytest


def _generate_random_email() -> str:
    return f"user_{uuid.uuid4().hex[:8]}@test.com"


async def test_register_user_success(client: AsyncClient):
    email = _generate_random_email()
    payload = {"email": email, "password": "securepassword123"}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["role"] == "USER"
    assert "password" not in data


async def test_register_duplicate_email_returns_bad_request(client: AsyncClient):

    email = _generate_random_email()
    payload = {"email": email, "password": "securepassword123"}

    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400

    error_data = res2.json()
    assert "already registered" in error_data["message"]


async def test_login_success(client: AsyncClient):
    email = _generate_random_email()
    password = "MyStrongPassword_99"

    await client.post("/api/v1/auth/register", json={"email": email, "password": password})

    login_payload = {"username": email, "password": password}
    response = await client.post("/api/v1/auth/login", data=login_payload)

    assert response.status_code == 200
    data = response.json()

    assert "accessToken" in data
    assert data["tokenType"] == "bearer"
    assert data["user"]["email"] == email
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


async def test_login_with_wrong_password_fails(client: AsyncClient):
    email = _generate_random_email()
    real_password = "realPassword"

    await client.post("/api/v1/auth/register", json={"email": email, "password": real_password})
    wrong_payload = {"username": email, "password": "wrongPassword123"}
    response = await client.post("/api/v1/auth/login", data=wrong_payload)

    assert response.status_code == 401


async def test_get_me_unauthorized_without_token(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_get_me_authorized_with_token(client: AsyncClient):
    email = _generate_random_email()
    password = "SuperSecretPassword123"

    await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_res = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = login_res.json()["accessToken"]

    headers = {"Authorization": f"Bearer {token}"}
    me_res = await client.get("/api/v1/auth/me", headers=headers)

    assert me_res.status_code == 200
    profile = me_res.json()
    assert profile["email"] == email
    assert profile["active"] is True
