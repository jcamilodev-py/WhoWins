from functools import cached_property
from typing import Self
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
DEFAULT_PASSWORDS = frozenset({"", "postgres", "changeme", "minioadmin"})


def _is_local(url: str) -> bool:
    return urlsplit(url).hostname in LOCAL_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "whowins"
    db_user: str = "postgres"
    db_password: str = "postgres"
    # Databases reached over the internet (Neon, Supabase, Render's external
    # URL) only accept encrypted connections; a private network does not need it.
    db_ssl: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    # Where Google sends the user back. Unset, it is derived from the request,
    # which is right when the browser talks to the API directly. Behind the
    # frontend's proxy the request arrives with the API's own host, so the
    # public address has to be given explicitly.
    oauth_redirect_base_url: str | None = None

    # Feeds MAIL_FROM, which validates as a real address: empty values and
    # reserved TLDs like .local both fail at import time.
    mail_username: str = "noreply@example.com"
    mail_password: str = ""

    frontend_url: str = "http://localhost:5173"

    # Deliberately has no default: a shipped fallback would let a deployment
    # sign tokens with a publicly known secret.
    jwt_secret: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Signs the session cookie authlib uses for the OAuth "state". Falls back
    # to jwt_secret when unset, so the app still starts.
    session_secret: str | None = None
    # That cookie only has to outlive the handshake with Google.
    session_max_age_seconds: int = 600

    cors_allowed_origins: str = "http://localhost:5173"

    # "memory://" is only correct with a single worker. In production use
    # e.g. "redis://localhost:6379" so the limit is shared across workers.
    rate_limit_storage_uri: str = "memory://"

    # Object storage (MinIO in development, S3/R2/Supabase in production).
    # Photos never pass through the backend: it only signs upload URLs.
    storage_endpoint_url: str = "http://localhost:9000"
    # The host the browser uses, when it differs from the one the backend uses
    # (Docker networks, private VPC endpoints). Signatures are tied to the host,
    # so presigned URLs are always signed with this one.
    storage_public_endpoint_url: str | None = None
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "whowins"
    # S3 requires a region name even when the server ignores it, as MinIO does.
    storage_region: str = "us-east-1"
    # Long enough to survive a slow mobile upload, short enough that a leaked URL expires.
    storage_upload_url_expire_seconds: int = 300
    storage_download_url_expire_seconds: int = 900
    # A presigned PUT cannot enforce a size, so this is checked after the upload.
    storage_max_upload_bytes: int = 5 * 1024 * 1024
    storage_allowed_image_types: str = "image/jpeg,image/png,image/webp"

    server_host: str = "127.0.0.1"
    server_port: int = 8000

    @property
    def database_url(self) -> str:
        # Built, not formatted: a generated password containing "@" or "/" would
        # otherwise corrupt the URL.
        return URL.create(
            "postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"ssl": "require"} if self.db_ssl else {},
        ).render_as_string(hide_password=False)

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in ("dev", "development")

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def storage_signing_endpoint(self) -> str:
        return self.storage_public_endpoint_url or self.storage_endpoint_url

    @cached_property
    def allowed_image_types(self) -> frozenset[str]:
        return frozenset(t.strip().lower() for t in self.storage_allowed_image_types.split(",") if t.strip())

    @property
    def session_signing_key(self) -> str:
        return self.session_secret or self.jwt_secret

    @model_validator(mode="after")
    def _refuse_unsafe_production_values(self) -> Self:
        """Fails the deploy instead of running production on development defaults.

        Every default below works locally, and a missing variable would otherwise
        go unnoticed until the first request that needs it.
        """
        if self.is_dev:
            return self
        checks = [
            (len(self.jwt_secret) < 32, "JWT_SECRET must be at least 32 characters"),
            (self.db_password in DEFAULT_PASSWORDS, "DB_PASSWORD is a development default"),
            (
                self.storage_access_key in DEFAULT_PASSWORDS or self.storage_secret_key in DEFAULT_PASSWORDS,
                "STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY are development defaults",
            ),
            (_is_local(self.storage_endpoint_url), "STORAGE_ENDPOINT_URL points to this machine"),
            (_is_local(self.frontend_url), "FRONTEND_URL points to this machine"),
            (any(_is_local(origin) for origin in self.cors_origins), "CORS_ALLOWED_ORIGINS allows this machine"),
        ]
        problems = [message for failed, message in checks if failed]
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


# Required fields are loaded from the environment at runtime (pydantic-settings),
# but mypy's synthesized __init__ still treats them as required call args.
settings = Settings()  # type: ignore[call-arg]
