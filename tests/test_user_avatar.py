import uuid

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.core.settings import settings
from app.shared.storage.object_storage import ObjectStorage
from app.user.models import AuthProvider, Role, User

PASSWORD = "UserPassword123"
IMAGE_BYTES = b"not-really-a-jpeg-but-bytes-are-bytes"


async def _create_user(db: AsyncSession) -> User:
    user = User(
        email=f"avatar_test_{uuid.uuid4().hex[:8]}@test.com",
        display_name="Avatar Tester",
        password=hash_password(PASSWORD),
        role=Role.USER,
        auth_provider=AuthProvider.LOCAL,
        email_verified=True,
        active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", data={"username": user.email, "password": PASSWORD})
    # The auth dependency reads the cookie before the header, so a leftover cookie
    # from an earlier login would decide who the user is.
    client.cookies.clear()
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def _upload_avatar(client: AsyncClient, headers: dict[str, str], keys: list[str], content_type="image/jpeg"):
    """Requests an upload URL and puts the bytes where it points, as the browser would."""
    ticket = await client.post(
        "/api/v1/users/me/avatar/upload-url", json={"contentType": content_type}, headers=headers
    )
    body = ticket.json()
    keys.append(body["key"])
    async with httpx.AsyncClient() as http:
        put = await http.put(body["uploadUrl"], content=IMAGE_BYTES, headers={"Content-Type": body["contentType"]})
    assert put.status_code == 200
    return body


# --- upload url ---


async def test_avatar_upload_url_without_token_returns_401(client: AsyncClient):
    response = await client.post("/api/v1/users/me/avatar/upload-url", json={"contentType": "image/jpeg"})
    assert response.status_code == 401


async def test_avatar_upload_url_is_scoped_to_the_current_user(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)

    response = await client.post(
        "/api/v1/users/me/avatar/upload-url",
        json={"contentType": "image/jpeg"},
        headers=await _login(client, user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key"].startswith(f"users/{user.id}/avatar/")
    assert body["key"].endswith(".jpg")
    assert body["contentType"] == "image/jpeg"
    assert body["maxBytes"] == settings.storage_max_upload_bytes


async def test_avatar_upload_url_rejects_a_non_image_type(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)

    response = await client.post(
        "/api/v1/users/me/avatar/upload-url",
        json={"contentType": "application/pdf"},
        headers=await _login(client, user),
    )

    assert response.status_code == 400


# --- confirming an upload ---


async def test_user_without_avatar_has_no_url(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session)

    response = await client.get("/api/v1/users/me", headers=await _login(client, user))

    assert response.json()["avatarUrl"] is None


async def test_confirmed_avatar_is_readable_through_the_returned_url(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    upload = await _upload_avatar(client, headers, uploaded_keys)

    confirm = await client.put("/api/v1/users/me/avatar", json={"key": upload["key"]}, headers=headers)

    assert confirm.status_code == 200
    avatar_url = confirm.json()["avatarUrl"]
    assert avatar_url is not None
    async with httpx.AsyncClient() as http:
        stored = await http.get(avatar_url)
    assert stored.status_code == 200
    assert stored.content == IMAGE_BYTES
    assert (await client.get("/api/v1/users/me", headers=headers)).json()["avatarUrl"] is not None


async def test_confirming_a_key_that_was_never_uploaded_returns_400(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage
):
    user = await _create_user(db_session)
    headers = await _login(client, user)

    response = await client.put(
        "/api/v1/users/me/avatar", json={"key": f"users/{user.id}/avatar/missing.jpg"}, headers=headers
    )

    assert response.status_code == 400


async def test_confirming_another_users_upload_returns_400(
    client: AsyncClient, db_session: AsyncSession, uploaded_keys: list[str]
):
    owner = await _create_user(db_session)
    upload = await _upload_avatar(client, await _login(client, owner), uploaded_keys)
    thief = await _create_user(db_session)
    thief_headers = await _login(client, thief)

    response = await client.put("/api/v1/users/me/avatar", json={"key": upload["key"]}, headers=thief_headers)

    assert response.status_code == 400
    assert (await client.get("/api/v1/users/me", headers=thief_headers)).json()["avatarUrl"] is None


async def test_oversized_upload_is_rejected_and_removed_from_storage(
    client: AsyncClient,
    db_session: AsyncSession,
    storage: ObjectStorage,
    uploaded_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    # Registered for cleanup even though the code under test should delete it:
    # if that code is ever broken, the test must fail without leaving the file behind.
    upload = await _upload_avatar(client, headers, uploaded_keys)
    monkeypatch.setattr(settings, "storage_max_upload_bytes", len(IMAGE_BYTES) - 1)

    response = await client.put("/api/v1/users/me/avatar", json={"key": upload["key"]}, headers=headers)

    assert response.status_code == 400
    # Rejected files must not sit in the bucket costing money and holding user data.
    assert await storage.stat(upload["key"]) is None


async def test_replacing_the_avatar_deletes_the_previous_file(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage, uploaded_keys: list[str]
):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    first = await _upload_avatar(client, headers, uploaded_keys)
    await client.put("/api/v1/users/me/avatar", json={"key": first["key"]}, headers=headers)
    second = await _upload_avatar(client, headers, uploaded_keys, content_type="image/png")

    response = await client.put("/api/v1/users/me/avatar", json={"key": second["key"]}, headers=headers)

    assert response.status_code == 200
    assert await storage.stat(first["key"]) is None
    assert await storage.stat(second["key"]) is not None


async def test_deleting_the_avatar_clears_the_url_and_the_file(
    client: AsyncClient, db_session: AsyncSession, storage: ObjectStorage, uploaded_keys: list[str]
):
    user = await _create_user(db_session)
    headers = await _login(client, user)
    # Registered for cleanup even though the endpoint should delete it: if the
    # deletion is ever broken, the test must fail without leaving the file behind.
    upload = await _upload_avatar(client, headers, uploaded_keys)
    await client.put("/api/v1/users/me/avatar", json={"key": upload["key"]}, headers=headers)

    response = await client.delete("/api/v1/users/me/avatar", headers=headers)

    assert response.status_code == 200
    assert response.json()["avatarUrl"] is None
    assert await storage.stat(upload["key"]) is None
