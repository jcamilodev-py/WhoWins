"""Display-name handling for Google logins.

These call AuthService directly instead of going through the endpoint: the real
route needs a round trip to Google's OAuth servers, which a test cannot make.
"""

import uuid

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password
from app.auth.service import AuthService
from app.user.models import AuthProvider, Role, User
from app.user.repository import UserRepository

auth_service = AuthService(UserRepository())


def _email() -> str:
    return f"google_test_{uuid.uuid4().hex[:8]}@test.com"


def _google_id() -> str:
    return f"google-{uuid.uuid4().hex}"


async def test_new_google_user_takes_the_google_name(db_session: AsyncSession):
    result = await auth_service.login_with_google(db_session, _email(), _google_id(), "Valentina Gómez", Response())

    assert result.user.display_name == "Valentina Gómez"


async def test_google_name_longer_than_40_characters_is_truncated(db_session: AsyncSession):
    long_name = "María Fernanda de los Ángeles Rodríguez Castillo"

    result = await auth_service.login_with_google(db_session, _email(), _google_id(), long_name, Response())

    assert result.user.display_name == long_name[:40].strip()
    assert result.user.display_name is not None
    assert len(result.user.display_name) <= 40


async def test_google_user_without_a_name_keeps_display_name_empty(db_session: AsyncSession):
    result = await auth_service.login_with_google(db_session, _email(), _google_id(), None, Response())

    assert result.user.display_name is None


async def test_blank_google_name_is_treated_as_missing(db_session: AsyncSession):
    result = await auth_service.login_with_google(db_session, _email(), _google_id(), "   ", Response())

    assert result.user.display_name is None


async def test_google_login_does_not_overwrite_a_chosen_display_name(db_session: AsyncSession):
    email = _email()
    db_session.add(
        User(
            email=email,
            display_name="Vale",
            password=hash_password("UserPassword123"),
            role=Role.USER,
            auth_provider=AuthProvider.LOCAL,
        )
    )
    await db_session.commit()

    result = await auth_service.login_with_google(db_session, email, _google_id(), "Valentina Gómez", Response())

    assert result.user.display_name == "Vale"


async def test_linking_google_fills_a_missing_display_name(db_session: AsyncSession):
    email = _email()
    db_session.add(
        User(
            email=email,
            display_name=None,
            password=hash_password("UserPassword123"),
            role=Role.USER,
            auth_provider=AuthProvider.LOCAL,
        )
    )
    await db_session.commit()

    result = await auth_service.login_with_google(db_session, email, _google_id(), "Valentina Gómez", Response())

    assert result.user.display_name == "Valentina Gómez"
