from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "whowins"
    db_user: str = "postgres"
    db_password: str = "postgres"

    google_client_id: str = ""
    google_client_secret: str = ""

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

    # Firma la cookie de sesión que authlib usa para el "state" de OAuth.
    # Si no se define cae en jwt_secret para que la app arranque igualmente.
    session_secret: str | None = None
    # Vida de esa cookie: solo tiene que sobrevivir al handshake con Google.
    session_max_age_seconds: int = 600

    cors_allowed_origins: str = "http://localhost:5173"

    # "memory://" solo es correcto con un unico worker. En produccion usar
    # p.ej. "redis://localhost:6379" para que el limite sea global.
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
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

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


# Required fields are loaded from the environment at runtime (pydantic-settings),
# but mypy's synthesized __init__ still treats them as required call args.
settings = Settings()  # type: ignore[call-arg]
