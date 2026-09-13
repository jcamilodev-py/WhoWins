from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, get_db
from app.core.limiter import limiter
from app.main import app


@pytest.fixture(autouse=True)
def disable_rate_limiter():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Each test gets its own connection-bound transaction. `join_transaction_mode="create_savepoint"`
    lets service code call `db.commit()` normally (it commits a SAVEPOINT, not the outer
    transaction) while the outer transaction is never committed, so closing the connection
    without committing rolls everything back — no test leaves data behind for the next one."""
    async with engine.connect() as connection:
        await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def _get_db_override() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        del app.dependency_overrides[get_db]
