from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    google_client_id: str
    google_client_secret: str

    mail_username: str
    mail_password: str

    frontend_url: str = "http://localhost:5173"

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
    def session_signing_key(self) -> str:
        return self.session_secret or self.jwt_secret


# Required fields are loaded from the environment at runtime (pydantic-settings),
# but mypy's synthesized __init__ still treats them as required call args.
settings = Settings()  # type: ignore[call-arg]
