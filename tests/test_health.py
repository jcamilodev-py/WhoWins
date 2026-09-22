import asyncio

import pytest
from httpx import AsyncClient

from app.core import health
from app.core.database import get_db
from app.main import app


async def test_health_returns_200_when_the_database_answers(client: AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def _use_database(session: object):
    previous = app.dependency_overrides[get_db]

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    return previous


async def test_health_returns_503_when_the_database_is_down(client: AsyncClient):
    class _RefusingSession:
        async def execute(self, *args, **kwargs):
            raise OSError("connection refused")

    previous = await _use_database(_RefusingSession())
    try:
        response = await client.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


async def test_health_answers_503_in_time_when_the_database_hangs(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _HangingSession:
        async def execute(self, *args, **kwargs):
            await asyncio.sleep(10)

    monkeypatch.setattr(health, "DATABASE_CHECK_TIMEOUT_SECONDS", 0.05)
    previous = await _use_database(_HangingSession())
    try:
        response = await asyncio.wait_for(client.get("/health"), timeout=2)
    finally:
        app.dependency_overrides[get_db] = previous

    assert response.status_code == 503


async def test_health_needs_no_token(client: AsyncClient):
    response = await client.get("/health", headers={"Authorization": "Bearer not-a-token"})

    assert response.status_code == 200
