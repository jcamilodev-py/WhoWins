"""Production configuration: what refuses to start, and what the app hides."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRODUCTION = {
    "env": "production",
    "jwt_secret": "a" * 43,
    "db_password": "a-generated-password",
    "storage_endpoint_url": "https://account.r2.cloudflarestorage.com",
    "storage_access_key": "real-access-key",
    "storage_secret_key": "real-secret-key",
    "frontend_url": "https://whowins.onrender.com",
    "cors_allowed_origins": "https://whowins.onrender.com",
}


def _production(**overrides) -> Settings:
    # _env_file=None: the developer's .env must not leak into what is being tested.
    return Settings(_env_file=None, **(PRODUCTION | overrides))  # type: ignore[call-arg]


def test_production_with_real_values_starts():
    assert _production().is_dev is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("jwt_secret", "too-short"),
        ("db_password", "postgres"),
        ("storage_access_key", "minioadmin"),
        ("storage_secret_key", "minioadmin"),
        ("storage_endpoint_url", "http://localhost:9000"),
        ("frontend_url", "http://localhost:5173"),
        ("cors_allowed_origins", "https://whowins.onrender.com,http://127.0.0.1:5173"),
    ],
)
def test_production_refuses_development_values(field: str, value: str):
    with pytest.raises(ValidationError, match="Refusing to start in production"):
        _production(**{field: value})


def test_development_starts_on_the_defaults():
    assert Settings(_env_file=None, env="dev", jwt_secret="x").is_dev is True  # type: ignore[call-arg]


def test_database_url_keeps_a_password_with_url_characters_intact():
    url = make_url(_production(db_password="p@ss/w%rd:#").database_url)

    assert url.password == "p@ss/w%rd:#"
    assert url.host == "localhost"


def test_database_url_requires_ssl_only_when_asked():
    assert make_url(_production(db_ssl=True).database_url).query == {"ssl": "require"}
    assert make_url(_production().database_url).query == {}


def test_production_app_hides_the_api_docs():
    # A fresh interpreter: the app reads its settings once, at import.
    environment = os.environ | {key.upper(): value for key, value in PRODUCTION.items()}
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(app.docs_url, app.redoc_url, app.openapi_url)"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["None", "None", "None"]


async def test_development_app_serves_the_api_docs(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
