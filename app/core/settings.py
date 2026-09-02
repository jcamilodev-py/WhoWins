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

    cors_allowed_origins: str = "http://localhost:5173"

    server_port: int = 8000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in ("dev", "development")


settings = Settings()