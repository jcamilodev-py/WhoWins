import socket
from collections.abc import AsyncGenerator, Generator
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, get_db
from app.core.limiter import limiter
from app.core.settings import settings
from app.main import app
from app.shared.storage.object_storage import ObjectStorage, object_storage


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


@pytest.fixture(scope="session")
def storage() -> ObjectStorage:
    """The real object storage, or a skip when it is not running.

    A plain socket probe, not an S3 call: botocore spends ~14 seconds retrying an
    endpoint that is not listening, which would slow the whole suite down.
    """
    endpoint = urlparse(settings.storage_signing_endpoint)
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((endpoint.hostname or "localhost", endpoint.port or 9000)) != 0:
            pytest.skip(f"Object storage is not listening on {settings.storage_signing_endpoint}")
    return object_storage


@pytest.fixture
def uploaded_keys(storage: ObjectStorage) -> Generator[list[str]]:
    """Keys to remove afterwards: the database rolls back after each test, storage does not."""
    keys: list[str] = []
    yield keys
    for key in keys:
        storage._client.delete_object(Bucket=storage.bucket, Key=key)
